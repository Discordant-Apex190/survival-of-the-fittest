from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict):
    """Shared graph state contract for all LangGraph pipelines."""

    seed_params: dict[str, Any]
    dominant_creature: dict[str, Any] | None
    parent_creature: dict[str, Any] | None
    fight_history: list[dict[str, Any]]

    concept: dict[str, Any] | None
    stats: dict[str, Any] | None
    abilities: list[dict[str, Any]] | None
    taunts: dict[str, list[str]] | None
    visual_descriptor: dict[str, Any] | None
    evolution_decision: dict[str, Any] | None
    evolution_analysis: dict[str, Any] | None
    evolution_new_ability: dict[str, Any] | None
    evolution_updated_lore: str | None
    counter_design: dict[str, Any] | None

    trigger_event: str | None
    simulation_snapshot: dict[str, Any] | None
    narrative_threads: list[str] | None
    commentary_lines: list[str] | None
    commentary_retry_count: int

    validation_errors: list[str]
    retry_count: int
    creature_id: str | None
