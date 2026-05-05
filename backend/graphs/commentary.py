"""Graph 4 — commentary_graph (The Chronicler)

Triggered every `commentary_interval` fights, or on milestone events.
Always runs as a FastAPI BackgroundTask — the simulation loop never awaits it.

Trigger priority: extinction > rival_spawned > win_streak > evolution > periodic

DAG:
  gather_context → identify_narrative → generate_commentary
    → validate_commentary
      ├── pass → write_commentary → broadcast_commentary → END
      └── fail → retry_commentary → generate_commentary (max 2 retries)
                └── (max retries hit) → END (failed, silent)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, StateGraph
from loguru import logger
from sqlmodel import Session

from backend.graphs.nodes.db import make_broadcast_commentary_node, make_write_commentary_node
from backend.graphs.nodes.gemini import (
    GeminiProvider,
    get_gemini_provider,
    make_gather_context_node,
    make_generate_commentary_node,
    make_identify_narrative_node,
)
from backend.graphs.nodes.validators import (
    node_retry_commentary_patch,
    node_validate_commentary,
    route_after_commentary_validate,
)
from backend.graphs.state import GraphState
from backend.ws.manager import ConnectionManager
from backend.ws.manager import manager as default_manager

GraphStateHook = Callable[[str, GraphState], None]

# Trigger priority order (lower index = higher priority)
TRIGGER_PRIORITY = ["extinction", "rival_spawned", "win_streak", "evolution", "periodic"]


@dataclass(slots=True)
class CommentaryResult:
    trigger: str
    lines: list[str]
    threads: list[str]
    retry_count: int
    graph_state: GraphState


def _build_initial_state(
    trigger_event: str,
    simulation_snapshot: dict[str, Any],
) -> GraphState:
    return {
        "seed_params": {},
        "dominant_creature": None,
        "parent_creature": None,
        "fight_history": [],
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
        "trigger_event": trigger_event,
        "simulation_snapshot": simulation_snapshot,
        "narrative_threads": None,
        "commentary_lines": None,
        "commentary_retry_count": 0,
        "validation_errors": [],
        "retry_count": 0,
        "creature_id": None,
    }


def _build_graph(
    session: Session,
    provider: GeminiProvider,
    ws_manager: ConnectionManager,
    max_retries: int,
) -> Any:
    graph: StateGraph = StateGraph(GraphState)

    graph.add_node("gather_context", make_gather_context_node(provider))
    graph.add_node("identify_narrative", make_identify_narrative_node(provider))
    graph.add_node("generate_commentary", make_generate_commentary_node(provider))
    graph.add_node("validate_commentary", node_validate_commentary)
    graph.add_node("retry_commentary", node_retry_commentary_patch)
    graph.add_node("write_commentary", make_write_commentary_node(session))
    graph.add_node("broadcast_commentary", make_broadcast_commentary_node(ws_manager))

    graph.set_entry_point("gather_context")
    graph.add_edge("gather_context", "identify_narrative")
    graph.add_edge("identify_narrative", "generate_commentary")
    graph.add_edge("generate_commentary", "validate_commentary")
    graph.add_conditional_edges(
        "validate_commentary",
        route_after_commentary_validate(max_retries),
        {
            "write_commentary": "write_commentary",
            "retry_commentary": "retry_commentary",
            "failed": END,
        },
    )
    graph.add_edge("retry_commentary", "generate_commentary")
    graph.add_edge("write_commentary", "broadcast_commentary")
    graph.add_edge("broadcast_commentary", END)

    return graph.compile()


def run_commentary_graph(
    session: Session,
    *,
    trigger_event: str,
    simulation_snapshot: dict[str, Any],
    provider: GeminiProvider | None = None,
    ws_manager: ConnectionManager | None = None,
    max_retries: int = 2,
    state_hook: GraphStateHook | None = None,
) -> CommentaryResult:
    if provider is None:
        provider = get_gemini_provider()
    if ws_manager is None:
        ws_manager = default_manager

    initial_state = _build_initial_state(trigger_event, simulation_snapshot)
    compiled = _build_graph(session, provider, ws_manager, max_retries)

    logger.bind(stage="commentary_start", trigger=trigger_event).info("commentary | start")

    final_state: GraphState = compiled.invoke(initial_state)

    if state_hook:
        state_hook("final", final_state)

    lines = final_state.get("commentary_lines") or []
    threads = final_state.get("narrative_threads") or []
    retry_count = final_state.get("commentary_retry_count", 0)

    if not lines:
        logger.bind(
            stage="commentary_failed",
            trigger=trigger_event,
            retries=retry_count,
            errors=final_state.get("validation_errors"),
        ).warning("commentary | failed after {} retries", retry_count)
    else:
        logger.bind(stage="commentary_done", trigger=trigger_event, lines=len(lines)).info(
            "commentary | complete"
        )

    return CommentaryResult(
        trigger=trigger_event,
        lines=lines,
        threads=threads,
        retry_count=retry_count,
        graph_state=final_state,
    )
