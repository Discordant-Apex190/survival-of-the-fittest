from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, StateGraph
from loguru import logger
from sqlmodel import Session

from backend.graphs.nodes.db import make_write_sqlite_node
from backend.graphs.nodes.gemini import (
    GeminiProvider,
    get_gemini_provider,
    make_concept_node,
    make_stats_node,
    make_taunts_node,
)
from backend.graphs.nodes.tts import node_queue_tts
from backend.graphs.nodes.validators import node_retry_patch, node_validate, route_after_validate
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


def _build_graph(session: Session, provider: GeminiProvider, max_retries: int) -> Any:
    graph: StateGraph = StateGraph(GraphState)

    graph.add_node("generate_concept", make_concept_node(provider))
    graph.add_node("generate_stats", make_stats_node(provider))
    graph.add_node("generate_taunts", make_taunts_node(provider))
    graph.add_node("validate", node_validate)
    graph.add_node("retry_patch", node_retry_patch)
    graph.add_node("write_sqlite", make_write_sqlite_node(session))
    graph.add_node("queue_tts", node_queue_tts)

    graph.set_entry_point("generate_concept")
    graph.add_edge("generate_concept", "generate_stats")
    graph.add_edge("generate_stats", "generate_taunts")
    graph.add_edge("generate_taunts", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate(max_retries),
        {"write_sqlite": "write_sqlite", "retry_patch": "retry_patch", "failed": END},
    )
    graph.add_edge("retry_patch", "generate_stats")
    graph.add_edge("write_sqlite", "queue_tts")
    graph.add_edge("queue_tts", END)

    return graph.compile()


def run_creature_factory_graph(
    session: Session,
    *,
    seed_params: dict[str, Any],
    provider: GeminiProvider | None = None,
    max_retries: int = 3,
    state_hook: GraphStateHook | None = None,
) -> CreatureFactoryResult:
    active_provider = provider or get_gemini_provider()
    initial_state = _build_initial_state(seed_params)

    logger.bind(
        stage="start",
        tier=seed_params.get("tier"),
        element=seed_params.get("element"),
    ).info("creature_factory | start")
    if state_hook:
        state_hook("start", initial_state)

    compiled = _build_graph(session, active_provider, max_retries)
    final_state: GraphState = compiled.invoke(initial_state)

    validation_errors: list[str] = final_state["validation_errors"]
    creature_id = final_state["creature_id"]

    if validation_errors or not creature_id:
        formatted = (
            "; ".join(validation_errors) if validation_errors else "unknown validation failure"
        )
        logger.bind(stage="failed", errors=validation_errors).error(
            "creature_factory | failed after retries"
        )
        raise ValueError(f"creature_factory validation failed: {formatted}")

    if state_hook:
        state_hook("complete", final_state)

    abilities: list[dict[str, Any]] = final_state["abilities"] or []
    taunts: dict[str, list[str]] = final_state["taunts"] or {}

    return CreatureFactoryResult(
        creature_id=creature_id,
        name=final_state["concept"]["name"],
        tier=seed_params["tier"],
        element=seed_params["element"],
        ability_count=len(abilities),
        taunt_count=sum(len(lines) for lines in taunts.values()),
        retry_count=final_state["retry_count"],
        graph_state=final_state,
    )
