"""Isolated unit tests for Graph 1 (creature_factory) LangGraph nodes.

Each test calls a node function directly with a hand-built state dict
(the make_state() helper pattern) so nodes stay pure and testable without
running the full compiled graph.
"""

from __future__ import annotations

from typing import Any

from backend.graphs.nodes.gemini import (
    MockGeminiProvider,
    make_concept_node,
    make_stats_node,
    make_taunts_node,
)
from backend.graphs.nodes.tts import node_queue_tts
from backend.graphs.nodes.validators import node_retry_patch, node_validate, route_after_validate

PROVIDER = MockGeminiProvider()

SEED_COMMON = {
    "element": "fire",
    "archetype": "berserker",
    "tier": "common",
    "biome": "volcanic",
    "stat_budget": 80,
}

SEED_RARE = {
    "element": "void",
    "archetype": "trickster",
    "tier": "rare",
    "biome": "rift",
    "stat_budget": 125,
}


def make_state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "seed_params": SEED_COMMON,
        "dominant_creature": None,
        "parent_creature": None,
        "fight_history": [],
        "concept": None,
        "stats": None,
        "abilities": None,
        "taunts": None,
        "visual_descriptor": None,
        "evolution_decision": None,
        "counter_design": None,
        "trigger_event": "creature_factory",
        "simulation_snapshot": None,
        "narrative_threads": None,
        "commentary_lines": None,
        "commentary_retry_count": 0,
        "validation_errors": [],
        "retry_count": 0,
        "creature_id": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# generate_concept node
# ---------------------------------------------------------------------------


def test_concept_node_returns_required_fields() -> None:
    node = make_concept_node(PROVIDER)
    result = node(make_state())

    assert "concept" in result
    assert "visual_descriptor" in result
    concept = result["concept"]
    for field in ("name", "lore", "personality", "fighting_style", "behavior_weights"):
        assert field in concept, f"concept missing: {field}"


def test_concept_node_is_deterministic() -> None:
    node = make_concept_node(PROVIDER)
    a = node(make_state())
    b = node(make_state())
    assert a["concept"]["name"] == b["concept"]["name"]


def test_concept_node_uses_seed_params() -> None:
    node = make_concept_node(PROVIDER)
    result_fire = node(make_state(seed_params=SEED_COMMON))
    result_void = node(make_state(seed_params=SEED_RARE))
    assert result_fire["concept"]["name"] != result_void["concept"]["name"]


# ---------------------------------------------------------------------------
# generate_stats node
# ---------------------------------------------------------------------------


def _concept_for(seed: dict[str, Any]) -> dict[str, Any]:
    return make_concept_node(PROVIDER)(make_state(seed_params=seed))["concept"]


def test_stats_node_budget_exact_common() -> None:
    concept = _concept_for(SEED_COMMON)
    node = make_stats_node(PROVIDER)
    result = node(make_state(seed_params=SEED_COMMON, concept=concept))

    stats = result["stats"]
    assert sum(stats.values()) == 80


def test_stats_node_budget_exact_rare() -> None:
    concept = _concept_for(SEED_RARE)
    node = make_stats_node(PROVIDER)
    result = node(make_state(seed_params=SEED_RARE, concept=concept))

    stats = result["stats"]
    assert sum(stats.values()) == 125


def test_stats_node_respects_max_single_stat_common() -> None:
    concept = _concept_for(SEED_COMMON)
    node = make_stats_node(PROVIDER)
    result = node(make_state(seed_params=SEED_COMMON, concept=concept))

    for name, value in result["stats"].items():
        assert value <= 25, f"{name}={value} exceeds common cap of 25"


def test_stats_node_ability_count_within_slots() -> None:
    concept = _concept_for(SEED_COMMON)
    node = make_stats_node(PROVIDER)
    result = node(make_state(seed_params=SEED_COMMON, concept=concept))

    assert 1 <= len(result["abilities"]) <= 1  # common max_slots=1, ability_count=min(1,2)


def test_stats_node_rare_ability_count_within_slots() -> None:
    concept = _concept_for(SEED_RARE)
    node = make_stats_node(PROVIDER)
    result = node(make_state(seed_params=SEED_RARE, concept=concept))

    assert 1 <= len(result["abilities"]) <= 3  # rare max_slots=3


# ---------------------------------------------------------------------------
# generate_taunts node
# ---------------------------------------------------------------------------


def test_taunts_node_returns_trigger_dict() -> None:
    concept = _concept_for(SEED_COMMON)
    node = make_taunts_node(PROVIDER)
    result = node(make_state(seed_params=SEED_COMMON, concept=concept))

    taunts = result["taunts"]
    assert isinstance(taunts, dict)
    for trigger, lines in taunts.items():
        assert isinstance(lines, list) and len(lines) >= 1, f"trigger '{trigger}' has no lines"


def test_taunts_node_references_creature_name() -> None:
    concept = _concept_for(SEED_COMMON)
    node = make_taunts_node(PROVIDER)
    result = node(make_state(seed_params=SEED_COMMON, concept=concept))

    all_text = " ".join(
        line for lines in result["taunts"].values() for line in lines
    )
    assert concept["name"] in all_text


# ---------------------------------------------------------------------------
# validate node
# ---------------------------------------------------------------------------


def _full_state_after_generation(seed: dict[str, Any] = SEED_COMMON) -> dict[str, Any]:
    concept = _concept_for(seed)
    stats_result = make_stats_node(PROVIDER)(make_state(seed_params=seed, concept=concept))
    taunts_result = make_taunts_node(PROVIDER)(make_state(seed_params=seed, concept=concept))
    return make_state(
        seed_params=seed,
        concept=concept,
        stats=stats_result["stats"],
        abilities=stats_result["abilities"],
        taunts=taunts_result["taunts"],
    )


def test_validate_node_passes_valid_state() -> None:
    state = _full_state_after_generation()
    result = node_validate(state)
    assert result["validation_errors"] == []


def test_validate_node_fails_missing_stats() -> None:
    state = _full_state_after_generation()
    state["stats"] = None
    result = node_validate(state)
    assert result["validation_errors"]


def test_validate_node_fails_budget_overflow() -> None:
    state = _full_state_after_generation()
    state["stats"] = {"health": 30, "attack": 30, "defense": 30, "speed": 30}  # total=120, want 80
    result = node_validate(state)
    assert any("budget" in e for e in result["validation_errors"])


def test_validate_node_fails_stat_exceeds_cap() -> None:
    state = _full_state_after_generation()
    # total = 80 but health=50 exceeds common cap of 25
    state["stats"] = {"health": 50, "attack": 10, "defense": 10, "speed": 10}
    result = node_validate(state)
    assert any("health" in e for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# route_after_validate
# ---------------------------------------------------------------------------


def test_route_passes_to_write_sqlite() -> None:
    route = route_after_validate(max_retries=3)
    state = make_state(validation_errors=[], retry_count=0)
    assert route(state) == "write_sqlite"


def test_route_retries_when_errors_and_budget_remains() -> None:
    route = route_after_validate(max_retries=3)
    state = make_state(validation_errors=["stats: budget mismatch"], retry_count=0)
    assert route(state) == "retry_patch"


def test_route_fails_when_retries_exhausted() -> None:
    route = route_after_validate(max_retries=3)
    state = make_state(validation_errors=["stats: budget mismatch"], retry_count=3)
    assert route(state) == "failed"


# ---------------------------------------------------------------------------
# retry_patch node
# ---------------------------------------------------------------------------


def test_retry_patch_increments_count() -> None:
    state = make_state(retry_count=1, validation_errors=["some error"])
    result = node_retry_patch(state)
    assert result["retry_count"] == 2


def test_retry_patch_clears_generated_fields() -> None:
    state = make_state(
        retry_count=0,
        stats={"health": 20},
        abilities=[{"name": "x"}],
        taunts={"win": ["ok"]},
        validation_errors=["oops"],
    )
    result = node_retry_patch(state)
    assert result["stats"] is None
    assert result["abilities"] is None
    assert result["taunts"] is None
    assert result["validation_errors"] == []


# ---------------------------------------------------------------------------
# queue_tts stub node
# ---------------------------------------------------------------------------


def test_tts_node_is_noop() -> None:
    state = make_state(creature_id="abc123")
    result = node_queue_tts(state)
    assert result == {}
