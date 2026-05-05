from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, StateGraph
from loguru import logger
from sqlmodel import Session

from backend.graphs.nodes.db import make_write_evolution_node
from backend.graphs.nodes.gemini import (
    GeminiProvider,
    get_gemini_provider,
    make_decide_evolution_node,
    make_generate_evolution_ability_node,
    make_update_lore_node,
    node_analyse_history,
)
from backend.graphs.nodes.validators import (
    node_retry_evolution_patch,
    node_validate_evolution_budget,
    route_after_evolution_validate,
)
from backend.graphs.state import GraphState

EVOLUTION_WIN_THRESHOLD = 3

GraphStateHook = Callable[[str, GraphState], None]


@dataclass(slots=True)
class EvolutionResult:
    creature_id: str
    parent_id: str
    name: str
    generation: int
    stat_boosts: dict[str, int]
    new_ability: bool
    retry_count: int
    graph_state: GraphState


def _build_initial_state(
    parent_creature: dict[str, Any],
    fight_history: list[dict[str, Any]],
) -> GraphState:
    return {
        "seed_params": {},
        "dominant_creature": None,
        "parent_creature": parent_creature,
        "fight_history": fight_history,
        "concept": None,
        "stats": None,
        "abilities": None,
        "taunts": None,
        "visual_descriptor": None,
        "evolution_decision": None,
        "evolution_analysis": None,
        "evolution_new_ability": None,
        "evolution_updated_lore": None,
        "counter_design": None,
        "trigger_event": "evolution",
        "simulation_snapshot": None,
        "narrative_threads": None,
        "commentary_lines": None,
        "commentary_retry_count": 0,
        "validation_errors": [],
        "retry_count": 0,
        "creature_id": None,
    }


def _route_after_decide(state: dict[str, Any]) -> str:
    if state["evolution_decision"].get("new_ability_slot"):
        return "generate_ability"
    return "update_lore"


def _build_graph(session: Session, provider: GeminiProvider, max_retries: int) -> Any:
    graph: StateGraph = StateGraph(GraphState)

    graph.add_node("analyse_history", node_analyse_history)
    graph.add_node("decide_evolution", make_decide_evolution_node(provider))
    graph.add_node("generate_ability", make_generate_evolution_ability_node(provider))
    graph.add_node("update_lore", make_update_lore_node(provider))
    graph.add_node("validate_budget", node_validate_evolution_budget)
    graph.add_node("retry_evolution", node_retry_evolution_patch)
    graph.add_node("write_evolution", make_write_evolution_node(session))

    graph.set_entry_point("analyse_history")
    graph.add_edge("analyse_history", "decide_evolution")
    graph.add_conditional_edges(
        "decide_evolution",
        _route_after_decide,
        {"generate_ability": "generate_ability", "update_lore": "update_lore"},
    )
    graph.add_edge("generate_ability", "update_lore")
    graph.add_edge("update_lore", "validate_budget")
    graph.add_conditional_edges(
        "validate_budget",
        route_after_evolution_validate(max_retries),
        {"write_evolution": "write_evolution", "retry_evolution": "retry_evolution", "failed": END},
    )
    graph.add_edge("retry_evolution", "decide_evolution")
    graph.add_edge("write_evolution", END)

    return graph.compile()


def run_evolution_graph(
    session: Session,
    *,
    parent_creature: dict[str, Any],
    fight_history: list[dict[str, Any]] | None = None,
    provider: GeminiProvider | None = None,
    max_retries: int = 3,
    state_hook: GraphStateHook | None = None,
) -> EvolutionResult:
    active_provider = provider or get_gemini_provider()
    initial_state = _build_initial_state(parent_creature, fight_history or [])

    logger.bind(
        stage="start",
        parent_id=parent_creature.get("id"),
        generation=parent_creature.get("generation"),
    ).info("evolution | start")

    if state_hook:
        state_hook("start", initial_state)

    compiled = _build_graph(session, active_provider, max_retries)
    final_state: GraphState = compiled.invoke(initial_state)

    validation_errors: list[str] = final_state["validation_errors"]
    child_id = final_state["creature_id"]

    if validation_errors or not child_id:
        formatted = (
            "; ".join(validation_errors) if validation_errors else "unknown evolution failure"
        )
        logger.bind(stage="failed", errors=validation_errors).error(
            "evolution | failed after retries"
        )
        raise ValueError(f"Evolution failed: {formatted}")

    decision = final_state["evolution_decision"] or {}
    logger.bind(stage="done", child_id=child_id).info("evolution | complete")

    return EvolutionResult(
        creature_id=child_id,
        parent_id=parent_creature["id"],
        name=parent_creature["name"],
        generation=parent_creature["generation"] + 1,
        stat_boosts=decision.get("stat_boosts", {}),
        new_ability=bool(final_state.get("evolution_new_ability")),
        retry_count=final_state["retry_count"],
        graph_state=final_state,
    )
