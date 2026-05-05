"""Graph 3 — rival_graph

Triggered when a creature hits the dominance threshold (default: 7 wins).
Generates a counter-archetype rival that is narratively and mechanically
aware of the dominant creature.

DAG:
  profile_dominant → design_counter → generate_rival → generate_taunts
    → validate_rival
      ├── pass  → write_rival → END
      └── fail  → retry_rival → generate_rival (max 2 retries)
                └── (max retries hit) → END (failed)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, StateGraph
from loguru import logger
from sqlmodel import Session

from backend.graphs.nodes.db import make_write_rival_node
from backend.graphs.nodes.gemini import (
    GeminiProvider,
    get_gemini_provider,
    make_design_counter_node,
    make_generate_rival_node,
    make_generate_rival_taunts_node,
    make_profile_dominant_node,
)
from backend.graphs.nodes.validators import (
    node_retry_rival_patch,
    node_validate_rival,
    route_after_rival_validate,
)
from backend.graphs.state import GraphState

RIVAL_DOMINANCE_THRESHOLD = 7

GraphStateHook = Callable[[str, GraphState], None]


@dataclass(slots=True)
class RivalResult:
    rival_id: str
    dominant_id: str
    rival_name: str
    counter_element: str
    counter_archetype: str
    retry_count: int
    graph_state: GraphState


def _build_initial_state(dominant_creature: dict[str, Any]) -> GraphState:
    return {
        "seed_params": {},
        "dominant_creature": dominant_creature,
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
        "trigger_event": "rival_spawned",
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

    graph.add_node("profile_dominant", make_profile_dominant_node(session))
    graph.add_node("design_counter", make_design_counter_node(provider))
    graph.add_node("generate_rival", make_generate_rival_node(provider))
    graph.add_node("generate_taunts", make_generate_rival_taunts_node(provider))
    graph.add_node("validate_rival", node_validate_rival)
    graph.add_node("retry_rival", node_retry_rival_patch)
    graph.add_node("write_rival", make_write_rival_node(session))

    graph.set_entry_point("profile_dominant")
    graph.add_edge("profile_dominant", "design_counter")
    graph.add_edge("design_counter", "generate_rival")
    graph.add_edge("generate_rival", "generate_taunts")
    graph.add_edge("generate_taunts", "validate_rival")
    graph.add_conditional_edges(
        "validate_rival",
        route_after_rival_validate(max_retries),
        {
            "write_rival": "write_rival",
            "retry_rival": "retry_rival",
            "failed": END,
        },
    )
    graph.add_edge("retry_rival", "generate_rival")
    graph.add_edge("write_rival", END)

    return graph.compile()


def run_rival_graph(
    session: Session,
    *,
    dominant_creature: dict[str, Any],
    provider: GeminiProvider | None = None,
    max_retries: int = 2,
    state_hook: GraphStateHook | None = None,
) -> RivalResult:
    if provider is None:
        provider = get_gemini_provider()

    initial_state = _build_initial_state(dominant_creature)
    compiled = _build_graph(session, provider, max_retries)

    logger.bind(
        stage="rival_start",
        dominant_id=dominant_creature["id"],
        dominant_wins=dominant_creature.get("wins"),
    ).info("rival | start")

    final_state: GraphState = compiled.invoke(initial_state)

    if state_hook:
        state_hook("final", final_state)

    rival_id = final_state.get("creature_id")
    if rival_id is None:
        raise ValueError(
            f"rival_graph failed for dominant {dominant_creature['id']} "
            f"after {final_state['retry_count']} retries: "
            f"{final_state.get('validation_errors')}"
        )

    counter_design = final_state.get("counter_design") or {}
    concept = final_state.get("concept") or {}

    logger.bind(
        stage="rival_done",
        dominant_id=dominant_creature["id"],
        rival_id=rival_id,
    ).info("rival | complete")

    return RivalResult(
        rival_id=rival_id,
        dominant_id=dominant_creature["id"],
        rival_name=concept.get("name", "Unknown Rival"),
        counter_element=counter_design.get("counter_element", ""),
        counter_archetype=counter_design.get("counter_archetype", ""),
        retry_count=final_state["retry_count"],
        graph_state=final_state,
    )
