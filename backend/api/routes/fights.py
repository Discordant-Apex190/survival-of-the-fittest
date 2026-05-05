from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.db.models import Creature, Fight, FightEvent
from backend.db.session import get_session
from backend.fight.engine import compute_win_probability
from backend.simulation.engine import step_matchmake

router = APIRouter(prefix="/fights", tags=["fights"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class FightSummary(BaseModel):
    id: str
    creature_a_id: str
    creature_b_id: str
    winner_id: str | None
    tier: str
    duration_turns: int
    created_at: datetime


class FightDetail(FightSummary):
    creature_a_name: str
    creature_a_element: str
    creature_b_name: str
    creature_b_element: str
    fight_log: dict[str, Any]


class FightEventOut(BaseModel):
    id: str
    fight_id: str
    turn: int
    event_type: str
    actor_id: str | None
    target_id: str | None
    ability_name: str | None
    damage: int | None
    hp_remaining: dict[str, Any]


class UpcomingFight(BaseModel):
    creature_a: dict[str, Any]
    creature_b: dict[str, Any]
    prob_a: float
    prob_b: float


class NoUpcomingFight(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# GET /fights
# ---------------------------------------------------------------------------


@router.get("", response_model=list[FightSummary])
def list_fights(
    session: Annotated[Session, Depends(get_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[FightSummary]:
    rows = session.exec(
        select(Fight).order_by(Fight.created_at.desc()).offset(offset).limit(limit)  # type: ignore[attr-defined]
    ).all()
    return [
        FightSummary(
            id=f.id,
            creature_a_id=f.creature_a_id,
            creature_b_id=f.creature_b_id,
            winner_id=f.winner_id,
            tier=f.tier,
            duration_turns=f.duration_turns,
            created_at=f.created_at,
        )
        for f in rows
    ]


# ---------------------------------------------------------------------------
# GET /fights/upcoming  — must be before /{fight_id}
# ---------------------------------------------------------------------------


@router.get("/upcoming", response_model=UpcomingFight | NoUpcomingFight)
def upcoming_fight(
    session: Annotated[Session, Depends(get_session)],
) -> UpcomingFight | NoUpcomingFight:
    matchmake = step_matchmake(session, fights_per_tick=1)
    if not matchmake.pairs:
        return NoUpcomingFight(message="no active creatures to match")

    a_id, b_id = matchmake.pairs[0]
    a = session.get(Creature, a_id)
    b = session.get(Creature, b_id)
    if a is None or b is None:
        return NoUpcomingFight(message="no active creatures to match")

    a_dict = {"id": a.id, "name": a.name, "tier": a.tier, "element": a.element, "stats": a.stats}
    b_dict = {"id": b.id, "name": b.name, "tier": b.tier, "element": b.element, "stats": b.stats}
    prob_a = compute_win_probability(
        {"stats": a.stats},
        {"stats": b.stats},
    )
    return UpcomingFight(
        creature_a=a_dict,
        creature_b=b_dict,
        prob_a=round(prob_a, 4),
        prob_b=round(1 - prob_a, 4),
    )


# ---------------------------------------------------------------------------
# GET /fights/{fight_id}
# ---------------------------------------------------------------------------


@router.get("/{fight_id}", response_model=FightDetail)
def get_fight(
    fight_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> FightDetail:
    fight = session.get(Fight, fight_id)
    if not fight:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fight not found")

    a = session.get(Creature, fight.creature_a_id)
    b = session.get(Creature, fight.creature_b_id)

    return FightDetail(
        id=fight.id,
        creature_a_id=fight.creature_a_id,
        creature_b_id=fight.creature_b_id,
        winner_id=fight.winner_id,
        tier=fight.tier,
        duration_turns=fight.duration_turns,
        created_at=fight.created_at,
        fight_log=fight.fight_log,
        creature_a_name=a.name if a else "unknown",
        creature_a_element=a.element if a else "unknown",
        creature_b_name=b.name if b else "unknown",
        creature_b_element=b.element if b else "unknown",
    )


# ---------------------------------------------------------------------------
# GET /fights/{fight_id}/events
# ---------------------------------------------------------------------------


@router.get("/{fight_id}/events", response_model=list[FightEventOut])
def get_fight_events(
    fight_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[FightEventOut]:
    if not session.get(Fight, fight_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fight not found")

    events = session.exec(
        select(FightEvent)
        .where(FightEvent.fight_id == fight_id)
        .order_by(FightEvent.turn, FightEvent.timestamp)  # type: ignore[attr-defined]
    ).all()

    return [
        FightEventOut(
            id=e.id,
            fight_id=e.fight_id,
            turn=e.turn,
            event_type=e.event_type,
            actor_id=e.actor_id,
            target_id=e.target_id,
            ability_name=e.ability_name,
            damage=e.damage,
            hp_remaining=e.hp_remaining,
        )
        for e in events
    ]
