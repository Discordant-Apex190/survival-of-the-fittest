from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlmodel import Session

from backend.graphs.nodes.db import write_creature_bundle
from backend.graphs.nodes.gemini import GeminiProvider, get_gemini_provider
from backend.graphs.nodes.validators import validate_generation_payload
from backend.graphs.state import GraphState

GraphStateHook = Callable[[str, GraphState], None]


@dataclass(slots=True)
class CreatureFactoryResult:
    creature_id: str
    name: str
    tier: str
    element: str
    ability_count: int
    taunt_count: int
    retry_count: int
    graph_state: GraphState


def _build_initial_state(seed_params: dict[str, Any]) -> GraphState:
    return {
        "seed_params": seed_params,
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


def _emit_state(stage: str, state: GraphState, hook: GraphStateHook | None) -> None:
    logger.bind(
        stage=stage,
        tier=state["seed_params"].get("tier"),
        retries=state["retry_count"],
        validation_errors=len(state["validation_errors"]),
    ).info("creature_factory stage")
    if hook:
        hook(stage, state)


def run_creature_factory_graph(
    session: Session,
    *,
    seed_params: dict[str, Any],
    provider: GeminiProvider | None = None,
    max_retries: int = 3,
    state_hook: GraphStateHook | None = None,
) -> CreatureFactoryResult:
    active_provider = provider or get_gemini_provider()
    state = _build_initial_state(seed_params)
    _emit_state("start", state, state_hook)

    concept = active_provider.generate_concept(seed_params)
    state["concept"] = concept
    state["visual_descriptor"] = concept.get("visual_descriptor")
    _emit_state("concept_generated", state, state_hook)

    retry_count = 0
    validation_errors: list[str] = []

    stats: dict[str, int] | None = None
    abilities: list[dict[str, Any]] | None = None
    taunts: dict[str, list[str]] | None = None

    for attempt in range(max_retries + 1):
        generated = active_provider.generate_stats(seed_params, concept)
        stats = generated.stats
        abilities = generated.abilities
        taunts = active_provider.generate_taunts(seed_params, concept)

        state["stats"] = stats
        state["abilities"] = abilities
        state["taunts"] = taunts

        validation_errors = validate_generation_payload(
            seed_params=seed_params,
            concept=concept,
            stats=stats,
            abilities=abilities,
            taunts=taunts,
        )
        state["validation_errors"] = validation_errors
        if not validation_errors:
            _emit_state("validated", state, state_hook)
            break

        retry_count = attempt + 1
        state["retry_count"] = retry_count
        _emit_state("retry", state, state_hook)

    if validation_errors or stats is None or abilities is None or taunts is None:
        formatted = (
            "; ".join(validation_errors) if validation_errors else "unknown validation failure"
        )
        _emit_state("failed", state, state_hook)
        raise ValueError(f"creature_factory validation failed: {formatted}")

    creature_id = write_creature_bundle(
        session,
        seed_params=seed_params,
        concept=concept,
        stats=stats,
        abilities=abilities,
        taunts=taunts,
    )
    state["creature_id"] = creature_id
    _emit_state("persisted", state, state_hook)

    return CreatureFactoryResult(
        creature_id=creature_id,
        name=concept["name"],
        tier=seed_params["tier"],
        element=seed_params["element"],
        ability_count=len(abilities),
        taunt_count=sum(len(lines) for lines in taunts.values()),
        retry_count=retry_count,
        graph_state=state,
    )
