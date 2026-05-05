from __future__ import annotations

from sqlmodel import Session, select

from backend.db.models import Creature, Fight, FightEvent
from backend.graphs.creature_factory import run_creature_factory_graph
from backend.simulation.engine import (
    TickResult,
    run_tick,
    step_fight,
    step_resolve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEED_PARAMS = {
    "element": "fire",
    "archetype": "berserker",
    "tier": "common",
    "biome": "volcanic",
    "stat_budget": 80,
}


def _generate_creature(session: Session) -> str:
    result = run_creature_factory_graph(session, seed_params=_SEED_PARAMS)
    return result.creature_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_step_fight_creates_fight_record(db_session: Session) -> None:
    a_id = _generate_creature(db_session)
    b_id = _generate_creature(db_session)

    result = step_fight(db_session, (a_id, b_id), seed="test-fight-record")

    fight = db_session.get(Fight, result.fight_id)
    assert fight is not None
    assert fight.winner_id in {a_id, b_id}
    assert fight.duration_turns >= 1


def test_step_fight_creates_fight_events(db_session: Session) -> None:
    a_id = _generate_creature(db_session)
    b_id = _generate_creature(db_session)

    result = step_fight(db_session, (a_id, b_id), seed="test-fight-events")

    events = db_session.exec(
        select(FightEvent).where(FightEvent.fight_id == result.fight_id)
    ).all()
    assert len(events) > 0
    assert events[-1].event_type == "ko"


def test_step_resolve_updates_scores(db_session: Session, sim_settings) -> None:
    a_id = _generate_creature(db_session)
    b_id = _generate_creature(db_session)

    fight_result = step_fight(db_session, (a_id, b_id), seed="test-resolve-scores")
    step_resolve(db_session, [fight_result], sim_settings)

    winner = db_session.get(Creature, fight_result.winner_id)
    loser = db_session.get(Creature, fight_result.loser_id)
    assert winner is not None and winner.wins == 1
    assert loser is not None and loser.losses == 1


def test_run_tick_returns_tick_result(db_session: Session, sim_settings) -> None:
    result = run_tick(db_session, sim_settings, fights_per_tick=1)
    assert isinstance(result, TickResult)
    assert isinstance(result.fights, list)
    assert isinstance(result.fight_count, int)
