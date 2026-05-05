from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.core.config import Settings, get_settings
from backend.db.models import Creature
from backend.db.session import get_session
from backend.graphs.commentary import run_commentary_graph
from backend.simulation.engine import (
    TickResult,
    run_tick,
)
from backend.ws.manager import manager

router = APIRouter(prefix="/simulation", tags=["simulation"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class FightResultOut(BaseModel):
    fight_id: str
    creature_a_id: str
    creature_b_id: str
    winner_id: str
    loser_id: str
    duration_turns: int


class PopulateOut(BaseModel):
    spawned: list[str]


class ResolveOut(BaseModel):
    evolved: list[str]
    rival_triggered: list[str]
    retired: list[str]


class TickResponse(BaseModel):
    populate: PopulateOut
    fights: list[FightResultOut]
    resolve: ResolveOut
    fight_count: int
    commentary_triggered: bool


class TickRequest(BaseModel):
    fights_per_tick: int = Field(default=3, ge=1, le=10)


# ---------------------------------------------------------------------------
# POST /simulation/tick
# ---------------------------------------------------------------------------


def _serialize_tick(result: TickResult) -> TickResponse:
    return TickResponse(
        populate=PopulateOut(spawned=result.populate.spawned),
        fights=[
            FightResultOut(
                fight_id=f.fight_id,
                creature_a_id=f.creature_a_id,
                creature_b_id=f.creature_b_id,
                winner_id=f.winner_id,
                loser_id=f.loser_id,
                duration_turns=f.duration_turns,
            )
            for f in result.fights
        ],
        resolve=ResolveOut(
            evolved=result.resolve.evolved,
            rival_triggered=result.resolve.rival_triggered,
            retired=result.resolve.retired,
        ),
        fight_count=result.fight_count,
        commentary_triggered=result.commentary_triggered,
    )


def _build_simulation_snapshot(session: Session) -> dict[str, Any]:
    """Build a lightweight snapshot of current sim state for commentary context."""
    top_creatures = session.exec(
        select(Creature)
        .where(Creature.status == "active")
        .order_by(Creature.wins.desc())  # type: ignore[arg-type]
        .limit(5)
    ).all()
    element_counts: dict[str, int] = {}
    for c in session.exec(select(Creature).where(Creature.status == "active")).all():
        element_counts[c.element] = element_counts.get(c.element, 0) + 1
    return {
        "top_creatures": [
            {"id": c.id, "name": c.name, "wins": c.wins, "element": c.element}
            for c in top_creatures
        ],
        "creature_names": [c.name for c in top_creatures],
        "element_counts": element_counts,
        "total_fights": 0,  # populated by gather_context node if needed
    }


def _run_commentary_background(
    session: Session,
    trigger_event: str,
    simulation_snapshot: dict[str, Any],
) -> None:
    """Sync wrapper called as FastAPI BackgroundTask."""
    try:
        run_commentary_graph(
            session,
            trigger_event=trigger_event,
            simulation_snapshot=simulation_snapshot,
        )
    except Exception as exc:  # noqa: BLE001
        from loguru import logger

        logger.bind(stage="commentary_bg", error=str(exc)).warning(
            "commentary background task failed silently"
        )


@router.post("/tick", response_model=TickResponse)
def tick(
    payload: TickRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TickResponse:
    result = run_tick(
        session,
        settings,
        fights_per_tick=payload.fights_per_tick,
        fight_count_for_commentary=payload.fights_per_tick,
    )

    snapshot = _build_simulation_snapshot(session)

    if result.commentary_triggered:
        background_tasks.add_task(
            _run_commentary_background, session, "periodic", snapshot
        )

    # Extinction events fire commentary too
    if result.resolve.retired:
        background_tasks.add_task(
            _run_commentary_background, session, "extinction", snapshot
        )

    # Rival spawn events
    if result.resolve.rival_triggered:
        background_tasks.add_task(
            _run_commentary_background, session, "rival_spawned", snapshot
        )

    # Evolution events
    if result.resolve.evolved:
        background_tasks.add_task(
            _run_commentary_background, session, "evolution", snapshot
        )

    # Broadcast updated leaderboard so connected clients stay in sync
    top_creatures = session.exec(
        select(Creature)
        .where(Creature.status == "active")
        .order_by(Creature.wins.desc())  # type: ignore[arg-type]
        .limit(20)
    ).all()
    manager.broadcast_sync({
        "type": "leaderboard_update",
        "data": [
            {
                "id": c.id,
                "name": c.name,
                "tier": c.tier,
                "element": c.element,
                "generation": c.generation,
                "wins": c.wins,
                "losses": c.losses,
                "status": c.status,
                "stats": c.stats,
                "fighting_style": c.fighting_style,
            }
            for c in top_creatures
        ],
    })

    return _serialize_tick(result)
