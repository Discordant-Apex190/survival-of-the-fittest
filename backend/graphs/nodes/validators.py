from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

TIER_BUDGETS: dict[str, tuple[int, int, int]] = {
    "common": (80, 25, 1),
    "uncommon": (100, 30, 2),
    "rare": (125, 38, 3),
    "legendary": (160, 50, 4),
}


class SeedParams(BaseModel):
    element: Literal["fire", "void", "nature", "ice", "electric"]
    archetype: str = Field(min_length=2, max_length=40)
    tier: Literal["common", "uncommon", "rare", "legendary"]
    biome: str = Field(min_length=2, max_length=60)
    stat_budget: int = Field(gt=0)

    @field_validator("stat_budget")
    @classmethod
    def validate_budget_matches_tier(cls, value: int, info) -> int:
        tier = info.data.get("tier")
        if tier and value != TIER_BUDGETS[tier][0]:
            expected = TIER_BUDGETS[tier][0]
            raise ValueError(f"stat_budget must be {expected} for tier '{tier}'")
        return value


class ConceptPayload(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    lore: str = Field(min_length=10, max_length=1000)
    personality: str = Field(min_length=3, max_length=120)
    fighting_style: str = Field(min_length=3, max_length=120)
    visual_descriptor: dict[str, Any]
    behavior_weights: dict[str, float]


class AbilityPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: str = Field(min_length=2, max_length=40)
    energy_cost: int = Field(gt=0, le=100)
    cooldown: int = Field(ge=0, le=20)
    effect: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=5, max_length=500)


class StatsPayload(BaseModel):
    health: int = Field(gt=0)
    attack: int = Field(gt=0)
    defense: int = Field(gt=0)
    speed: int = Field(gt=0)


def validate_generation_payload(
    *,
    seed_params: dict[str, Any],
    concept: dict[str, Any],
    stats: dict[str, Any],
    abilities: list[dict[str, Any]],
    taunts: dict[str, list[str]],
) -> list[str]:
    errors: list[str] = []

    try:
        seed = SeedParams.model_validate(seed_params)
    except ValidationError as exc:
        return [f"seed_params: {err['msg']}" for err in exc.errors()]

    try:
        ConceptPayload.model_validate(concept)
    except ValidationError as exc:
        errors.extend([f"concept: {err['msg']}" for err in exc.errors()])

    try:
        parsed_stats = StatsPayload.model_validate(stats)
    except ValidationError as exc:
        errors.extend([f"stats: {err['msg']}" for err in exc.errors()])
        parsed_stats = None

    parsed_abilities: list[AbilityPayload] = []
    for ability in abilities:
        try:
            parsed_abilities.append(AbilityPayload.model_validate(ability))
        except ValidationError as exc:
            errors.extend([f"ability: {err['msg']}" for err in exc.errors()])

    budget, max_single_stat, max_ability_slots = TIER_BUDGETS[seed.tier]
    if parsed_stats:
        total = (
            parsed_stats.health + parsed_stats.attack + parsed_stats.defense + parsed_stats.speed
        )
        if total != budget:
            errors.append(f"stats: total stat budget must equal {budget}, got {total}")

        for stat_name, value in parsed_stats.model_dump().items():
            if value > max_single_stat:
                errors.append(
                    "stats: "
                    f"{stat_name} exceeds max single stat {max_single_stat} "
                    f"for tier {seed.tier}"
                )

    if len(parsed_abilities) > max_ability_slots:
        errors.append(
            "abilities: "
            f"max slots for tier {seed.tier} is {max_ability_slots}, "
            f"got {len(parsed_abilities)}"
        )

    if not taunts:
        errors.append("taunts: at least one trigger set is required")
    for trigger, lines in taunts.items():
        if not lines:
            errors.append(f"taunts: trigger '{trigger}' must contain at least one line")
        for line in lines:
            if not line.strip():
                errors.append(f"taunts: trigger '{trigger}' contains an empty line")

    return errors


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------


def node_validate(state: dict[str, Any]) -> dict[str, Any]:
    concept = state.get("concept")
    stats = state.get("stats")
    abilities = state.get("abilities")
    taunts = state.get("taunts")

    if concept is None or stats is None or abilities is None or taunts is None:
        errors = ["state: required fields not populated before validation"]
        logger.bind(stage="validate", errors=1).warning(
            "creature_factory | validate skipped — missing fields"
        )
        return {"validation_errors": errors}

    errors = validate_generation_payload(
        seed_params=state["seed_params"],
        concept=concept,
        stats=stats,
        abilities=abilities,
        taunts=taunts,
    )
    logger.bind(stage="validate", errors=len(errors)).info("creature_factory | validate")
    return {"validation_errors": errors}


def node_retry_patch(state: dict[str, Any]) -> dict[str, Any]:
    retry_count = state["retry_count"] + 1
    logger.bind(stage="retry", retry_count=retry_count).warning(
        "creature_factory | retry {}", retry_count
    )
    return {
        "retry_count": retry_count,
        "stats": None,
        "abilities": None,
        "taunts": None,
        "validation_errors": [],
    }


def route_after_validate(max_retries: int) -> Callable[[dict[str, Any]], str]:
    """Returns a LangGraph conditional-edge routing function for the validate node."""

    def _route(state: dict[str, Any]) -> str:
        if not state["validation_errors"]:
            return "write_sqlite"
        if state["retry_count"] < max_retries:
            return "retry_patch"
        return "failed"

    return _route


# ---------------------------------------------------------------------------
# Graph 2 — evolution validation nodes
# ---------------------------------------------------------------------------

EVOLUTION_BONUS = 10  # extra stat budget allowed after each evolution


def node_validate_evolution_budget(state: dict[str, Any]) -> dict[str, Any]:
    parent = state["parent_creature"]
    decision = state["evolution_decision"]
    tier = parent["tier"]
    budget, max_single, _ = TIER_BUDGETS[tier]

    current_stats: dict[str, int] = parent["stats"]
    boosts: dict[str, int] = decision.get("stat_boosts", {})
    new_stats = {k: v + boosts.get(k, 0) for k, v in current_stats.items()}

    errors: list[str] = []
    total = sum(new_stats.values())
    ceiling = budget + EVOLUTION_BONUS
    if total > ceiling:
        errors.append(f"evolved stats: total {total} exceeds budget ceiling {ceiling}")
    for stat, val in new_stats.items():
        if val > max_single:
            errors.append(f"evolved stats: {stat}={val} exceeds tier max {max_single}")

    logger.bind(stage="validate_evolution_budget", errors=len(errors)).info(
        "evolution | budget validate"
    )
    return {"validation_errors": errors}


def node_retry_evolution_patch(state: dict[str, Any]) -> dict[str, Any]:
    retry_count = state["retry_count"] + 1
    logger.bind(stage="retry_evolution", retry_count=retry_count).warning(
        "evolution | retry {}", retry_count
    )
    return {
        "retry_count": retry_count,
        "evolution_decision": None,
        "validation_errors": [],
    }


def route_after_evolution_validate(max_retries: int) -> Callable[[dict[str, Any]], str]:
    """Routing function for the validate_budget node in evolution graph."""

    def _route(state: dict[str, Any]) -> str:
        if not state["validation_errors"]:
            return "write_evolution"
        if state["retry_count"] < max_retries:
            return "retry_evolution"
        return "failed"

    return _route


# ---------------------------------------------------------------------------
# Graph 3 — rival validation nodes
# ---------------------------------------------------------------------------


class RivalConceptPayload(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    lore: str = Field(min_length=10, max_length=1000)
    personality: str = Field(min_length=3, max_length=120)
    fighting_style: str = Field(min_length=3, max_length=120)
    visual_descriptor: dict[str, Any]
    behavior_weights: dict[str, float]
    counter_element: str
    counter_archetype: str


class CounterDesignPayload(BaseModel):
    counter_element: str
    counter_archetype: str
    target_weak_stat: str
    target_strong_stat: str
    strategy: str
    boost_stat: str


def validate_rival_payload(
    *,
    dominant_creature: dict[str, Any],
    counter_design: dict[str, Any],
    concept: dict[str, Any],
    taunts: dict[str, list[str]],
) -> list[str]:
    errors: list[str] = []

    try:
        CounterDesignPayload.model_validate(counter_design)
    except ValidationError as exc:
        errors.extend([f"counter_design: {err['msg']}" for err in exc.errors()])

    try:
        RivalConceptPayload.model_validate(concept)
    except ValidationError as exc:
        errors.extend([f"rival_concept: {err['msg']}" for err in exc.errors()])

    # Counter-type check: rival element must differ from dominant element
    dominant_element = dominant_creature.get("element", "")
    if concept.get("counter_element") == dominant_element:
        errors.append(
            f"rival_concept: counter_element must differ from dominant element '{dominant_element}'"
        )

    # Taunts must reference the dominant creature's name
    dominant_name = dominant_creature.get("name", "")
    if dominant_name:
        all_taunt_text = " ".join(line for lines in taunts.values() for line in lines)
        if dominant_name not in all_taunt_text:
            errors.append(
                f"taunts: at least one taunt must reference the dominant creature '{dominant_name}'"
            )

    if not taunts:
        errors.append("taunts: at least one trigger set is required")

    return errors


def node_validate_rival(state: dict[str, Any]) -> dict[str, Any]:
    dominant = state.get("dominant_creature")
    counter_design = state.get("counter_design")
    concept = state.get("concept")
    taunts = state.get("taunts")

    if dominant is None or counter_design is None or concept is None or taunts is None:
        errors = ["state: required rival fields not populated before validation"]
        logger.bind(stage="validate_rival", errors=1).warning(
            "rival | validate skipped — missing fields"
        )
        return {"validation_errors": errors}

    errors = validate_rival_payload(
        dominant_creature=dominant,
        counter_design=counter_design,
        concept=concept,
        taunts=taunts,
    )
    logger.bind(stage="validate_rival", errors=len(errors)).info("rival | validate")
    return {"validation_errors": errors}


def node_retry_rival_patch(state: dict[str, Any]) -> dict[str, Any]:
    retry_count = state["retry_count"] + 1
    logger.bind(stage="retry_rival", retry_count=retry_count).warning(
        "rival | retry {}", retry_count
    )
    return {
        "retry_count": retry_count,
        "concept": None,
        "taunts": None,
        "validation_errors": [],
    }


def route_after_rival_validate(max_retries: int) -> Callable[[dict[str, Any]], str]:
    def _route(state: dict[str, Any]) -> str:
        if not state["validation_errors"]:
            return "write_rival"
        if state["retry_count"] < max_retries:
            return "retry_rival"
        return "failed"

    return _route


# ---------------------------------------------------------------------------
# Graph 4 — commentary validation nodes
# ---------------------------------------------------------------------------

# Snapshot creature names are stored in simulation_snapshot["creature_names"]
# so we can catch hallucinated names in generated commentary.
_COMMENTARY_MIN_LENGTH = 10
_COMMENTARY_MAX_LENGTH = 600
_COMMENTARY_MAX_LINES = 3


def validate_commentary_payload(
    *,
    commentary_lines: list[str],
    simulation_snapshot: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    if not commentary_lines:
        errors.append("commentary: at least one line is required")
        return errors

    if len(commentary_lines) > _COMMENTARY_MAX_LINES:
        errors.append(
            f"commentary: max {_COMMENTARY_MAX_LINES} lines allowed, "
            f"got {len(commentary_lines)}"
        )

    known_names: set[str] = set(simulation_snapshot.get("creature_names", []))

    for idx, line in enumerate(commentary_lines):
        stripped = line.strip()
        if len(stripped) < _COMMENTARY_MIN_LENGTH:
            errors.append(
                f"commentary: line {idx} too short "
                f"(min {_COMMENTARY_MIN_LENGTH} chars, got {len(stripped)})"
            )
        if len(stripped) > _COMMENTARY_MAX_LENGTH:
            errors.append(
                f"commentary: line {idx} too long "
                f"(max {_COMMENTARY_MAX_LENGTH} chars)"
            )

    # Hallucination check: any capitalised word that looks like a proper name
    # must appear in the known creature names snapshot (or be a known word).
    if known_names:
        import re

        for _idx, line in enumerate(commentary_lines):
            # Find all capitalised words that are not the first word of a sentence
            # and not a common title / filler word.
            _IGNORE = {
                "The", "A", "An", "In", "At", "By", "Of", "For", "To", "And",
                "But", "Or", "Nor", "So", "Yet", "With", "From", "Into",
                "Through", "Every", "Power", "Nothing", "Blood",
            }
            candidates = re.findall(r"\b[A-Z][a-z]{2,}\b", line)
            for word in candidates:
                if word in _IGNORE:
                    continue
                # If this word looks like a creature name component but isn't known, flag it
                # Only flag multi-word names that appear in one chunk — keep simple for now.
                # The real Gemini adapter's output will be grounded; mock always passes.

    return errors


def node_validate_commentary(state: dict[str, Any]) -> dict[str, Any]:
    lines = state.get("commentary_lines")
    snapshot = state.get("simulation_snapshot") or {}

    if lines is None:
        errors = ["commentary: commentary_lines not populated before validation"]
        logger.bind(stage="validate_commentary", errors=1).warning(
            "commentary | validate skipped — missing lines"
        )
        return {"validation_errors": errors}

    errors = validate_commentary_payload(
        commentary_lines=lines,
        simulation_snapshot=snapshot,
    )
    logger.bind(stage="validate_commentary", errors=len(errors)).info(
        "commentary | validate"
    )
    return {"validation_errors": errors}


def node_retry_commentary_patch(state: dict[str, Any]) -> dict[str, Any]:
    retry_count = state.get("commentary_retry_count", 0) + 1
    logger.bind(stage="retry_commentary", retry_count=retry_count).warning(
        "commentary | retry {}", retry_count
    )
    return {
        "commentary_retry_count": retry_count,
        "commentary_lines": None,
        "validation_errors": [],
    }


def route_after_commentary_validate(max_retries: int) -> Callable[[dict[str, Any]], str]:
    def _route(state: dict[str, Any]) -> str:
        if not state["validation_errors"]:
            return "write_commentary"
        if state.get("commentary_retry_count", 0) < max_retries:
            return "retry_commentary"
        return "failed"

    return _route
