"""Spectator betting — in-memory vote store per fight.

The store resets whenever the active fight_id changes. Votes are pure
in-process state (no persistence needed — this is entertainment, not finance).
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.db.models import Creature, Fight
from backend.db.session import get_session
from backend.fight.engine import compute_win_probability
from backend.simulation.engine import step_matchmake
from backend.ws.manager import manager

router = APIRouter(prefix="/betting", tags=["betting"])


# ---------------------------------------------------------------------------
# In-memory vote store
# ---------------------------------------------------------------------------


class _VoteStore:
    """Thread-safe in-memory tally.  Resets when a new fight_id is observed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fight_id: str | None = None
        self._votes: dict[str, int] = {}

    def cast(self, fight_id: str, creature_id: str) -> dict[str, int]:
        with self._lock:
            if fight_id != self._fight_id:
                self._fight_id = fight_id
                self._votes = {}
            self._votes[creature_id] = self._votes.get(creature_id, 0) + 1
            return dict(self._votes)

    def state(self, fight_id: str) -> dict[str, int]:
        with self._lock:
            if fight_id != self._fight_id:
                return {}
            return dict(self._votes)


_store = _VoteStore()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class BettingState(BaseModel):
    fight_id: str
    creature_a_id: str
    creature_a_name: str
    creature_a_element: str
    creature_b_id: str
    creature_b_name: str
    creature_b_element: str
    prob_a: float
    prob_b: float
    votes_a: int
    votes_b: int
    total_votes: int


class NoBetting(BaseModel):
    message: str


class VoteRequest(BaseModel):
    fight_id: str
    creature_id: str


class VoteResponse(BaseModel):
    fight_id: str
    creature_id: str
    votes_a: int
    votes_b: int
    total_votes: int


# ---------------------------------------------------------------------------
# GET /betting/current
# ---------------------------------------------------------------------------


@router.get("/current", response_model=BettingState | NoBetting)
def current_bet_state(
    session: Annotated[Session, Depends(get_session)],
) -> BettingState | NoBetting:
    """Return the upcoming fight and current vote tally."""
    matchmake = step_matchmake(session, fights_per_tick=1)
    if not matchmake.pairs:
        return NoBetting(message="No upcoming fight available")

    a_id, b_id = matchmake.pairs[0]
    a = session.get(Creature, a_id)
    b = session.get(Creature, b_id)
    if a is None or b is None:
        return NoBetting(message="No upcoming fight available")

    # Use a stable fight_id derived from sorted pair so it's consistent
    fight_id = "_".join(sorted([a_id, b_id]))
    votes = _store.state(fight_id)

    prob_a = compute_win_probability({"stats": a.stats}, {"stats": b.stats})

    return BettingState(
        fight_id=fight_id,
        creature_a_id=a_id,
        creature_a_name=a.name,
        creature_a_element=a.element,
        creature_b_id=b_id,
        creature_b_name=b.name,
        creature_b_element=b.element,
        prob_a=round(prob_a, 4),
        prob_b=round(1 - prob_a, 4),
        votes_a=votes.get(a_id, 0),
        votes_b=votes.get(b_id, 0),
        total_votes=sum(votes.values()),
    )


# ---------------------------------------------------------------------------
# POST /betting/vote
# ---------------------------------------------------------------------------


@router.post("/vote", response_model=VoteResponse, status_code=status.HTTP_200_OK)
async def cast_vote(
    payload: VoteRequest,
    session: Annotated[Session, Depends(get_session)],
) -> VoteResponse:
    """Cast a vote for a creature in the current fight."""
    # Verify the creature exists and is active
    creature = session.get(Creature, payload.creature_id)
    if not creature or creature.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creature not found or not active",
        )

    votes = _store.cast(payload.fight_id, payload.creature_id)

    # Determine the other creature in this pair
    parts = payload.fight_id.split("_")
    other_id = next((p for p in parts if p != payload.creature_id), None)

    votes_a = votes.get(payload.creature_id, 0)
    votes_b = votes.get(other_id, 0) if other_id else 0

    # Broadcast updated tally via WebSocket
    await manager.broadcast(
        {
            "type": "vote_update",
            "fight_id": payload.fight_id,
            "votes": votes,
        }
    )

    return VoteResponse(
        fight_id=payload.fight_id,
        creature_id=payload.creature_id,
        votes_a=votes_a,
        votes_b=votes_b,
        total_votes=sum(votes.values()),
    )
