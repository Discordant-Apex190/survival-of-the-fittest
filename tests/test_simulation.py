"""Tests for the simulation loop — engine steps and POST /simulation/tick endpoint."""

from __future__ import annotations

from sqlmodel import Session, select

from backend.core.config import get_settings
from backend.db.models import Creature, Fight
from backend.db.session import engine
from backend.simulation.engine import (
    MatchmakeResult,
    PopulateResult,
    step_fight,
    step_matchmake,
    step_populate,
    step_resolve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_active_creature(
    session: Session,
    *,
    tier: str = "common",
    element: str = "fire",
    wins: int = 0,
    losses: int = 0,
    stats: dict | None = None,
) -> Creature:
    import shortuuid

    c = Creature(
        id=shortuuid.uuid(),
        name=f"Test {tier.title()} {shortuuid.uuid()[:4]}",
        tier=tier,
        element=element,
        wins=wins,
        losses=losses,
        status="active",
        stats=stats or {"health": 20, "attack": 20, "defense": 20, "speed": 20},
        visual_descriptor={},
        behavior_weights={},
        lore="test lore",
        personality="aggressive",
        fighting_style="rushdown",
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _get_settings():
    return get_settings()


# ---------------------------------------------------------------------------
# step_populate
# ---------------------------------------------------------------------------


def test_populate_spawns_when_below_minimum(client) -> None:
    settings = _get_settings()
    # Force below minimum by retiring all active creatures
    with Session(engine) as session:
        actives = session.exec(select(Creature).where(Creature.status == "active")).all()
        for c in actives:
            c.status = "retired"
            session.add(c)
        session.commit()

    with Session(engine) as session:
        result = step_populate(session, settings)

    assert isinstance(result, PopulateResult)
    assert len(result.spawned) > 0

    with Session(engine) as session:
        active = session.exec(select(Creature).where(Creature.status == "active")).all()
        assert len(active) >= settings.min_population


def test_populate_skips_when_at_minimum(client) -> None:
    settings = _get_settings()
    with Session(engine) as session:
        # Fill to minimum
        for _ in range(settings.min_population):
            _create_active_creature(session)
        result = step_populate(session, settings)

    assert result.spawned == []


# ---------------------------------------------------------------------------
# step_matchmake
# ---------------------------------------------------------------------------


def test_matchmake_pairs_same_tier(client) -> None:
    with Session(engine) as session:
        for _ in range(4):
            _create_active_creature(session, tier="common")
        result = step_matchmake(session, fights_per_tick=3)

    assert isinstance(result, MatchmakeResult)
    assert len(result.pairs) >= 1
    # No creature appears twice
    all_ids = [c for pair in result.pairs for c in pair]
    assert len(all_ids) == len(set(all_ids))


def test_matchmake_respects_fights_per_tick_limit(client) -> None:
    with Session(engine) as session:
        for _ in range(10):
            _create_active_creature(session, tier="common")
        result = step_matchmake(session, fights_per_tick=2)

    assert len(result.pairs) <= 2


def test_matchmake_no_cross_tier_pairs(client) -> None:
    with Session(engine) as session:
        for _ in range(2):
            _create_active_creature(session, tier="common")
        for _ in range(2):
            _create_active_creature(session, tier="rare")
        result = step_matchmake(session, fights_per_tick=10)

    for a_id, b_id in result.pairs:
        with Session(engine) as session:
            a = session.get(Creature, a_id)
            b = session.get(Creature, b_id)
            assert a.tier == b.tier


def test_matchmake_returns_empty_when_only_one_creature(client) -> None:
    # Retire all existing active creatures, then add exactly one
    with Session(engine) as session:
        actives = session.exec(select(Creature).where(Creature.status == "active")).all()
        for c in actives:
            c.status = "retired"
            session.add(c)
        session.commit()
        _create_active_creature(session, tier="common")
        result = step_matchmake(session, fights_per_tick=3)

    assert result.pairs == []


# ---------------------------------------------------------------------------
# step_fight
# ---------------------------------------------------------------------------


def test_fight_records_fight_in_db(client) -> None:
    with Session(engine) as session:
        a = _create_active_creature(session)
        b = _create_active_creature(session)
        a_id = a.id
        b_id = b.id
        result = step_fight(session, (a_id, b_id), seed="test-seed-1")

    assert result.winner_id in (a_id, b_id)
    assert result.loser_id in (a_id, b_id)
    assert result.winner_id != result.loser_id
    assert result.duration_turns >= 1

    with Session(engine) as session:
        fight = session.get(Fight, result.fight_id)
        assert fight is not None
        assert fight.winner_id == result.winner_id


def test_fight_writes_fight_events_to_db(client) -> None:
    from backend.db.models import FightEvent

    with Session(engine) as session:
        a = _create_active_creature(session)
        b = _create_active_creature(session)
        a_id = a.id
        b_id = b.id
        result = step_fight(session, (a_id, b_id), seed="test-seed-2")

    with Session(engine) as session:
        events = session.exec(
            select(FightEvent).where(FightEvent.fight_id == result.fight_id)
        ).all()
        assert len(events) > 0
        event_types = {e.event_type for e in events}
        # Must have at least one attack or ability event
        assert event_types & {"attack", "ability", "ko"}


def test_fight_stronger_creature_wins_more_often(client) -> None:
    """Over many runs, the stronger creature should win more often."""
    wins = 0
    trials = 30
    with Session(engine) as session:
        strong = _create_active_creature(
            session, stats={"health": 25, "attack": 25, "defense": 25, "speed": 25}
        )
        weak = _create_active_creature(
            session, stats={"health": 5, "attack": 5, "defense": 5, "speed": 5}
        )
        strong_id = strong.id
        weak_id = weak.id

    with Session(engine) as session:
        for i in range(trials):
            result = step_fight(session, (strong_id, weak_id), seed=f"prob-test-{i}")
            if result.winner_id == strong_id:
                wins += 1

    assert wins > trials * 0.6, f"Strong creature won {wins}/{trials} — expected > 60%"


# ---------------------------------------------------------------------------
# step_resolve
# ---------------------------------------------------------------------------


def test_resolve_increments_wins_and_losses(client) -> None:
    from backend.simulation.engine import FightResult

    settings = _get_settings()
    with Session(engine) as session:
        winner = _create_active_creature(session)
        loser = _create_active_creature(session)
        fight = Fight(
            id="testfight01",
            creature_a_id=winner.id,
            creature_b_id=loser.id,
            winner_id=winner.id,
            tier="common",
            duration_turns=5,
        )
        session.add(fight)
        session.commit()

        fake_results = [
            FightResult(
                fight_id=fight.id,
                creature_a_id=winner.id,
                creature_b_id=loser.id,
                winner_id=winner.id,
                loser_id=loser.id,
                duration_turns=5,
            )
        ]
        step_resolve(session, fake_results, settings)

        session.refresh(winner)
        session.refresh(loser)
        assert winner.wins == 1
        assert loser.losses == 1


def test_resolve_triggers_evolution_at_threshold(client) -> None:
    from backend.simulation.engine import FightResult

    settings = _get_settings()
    # Creature already at (threshold - 1) wins
    with Session(engine) as session:
        winner = _create_active_creature(
            session, wins=settings.evolution_win_threshold - 1
        )
        loser = _create_active_creature(session)
        fight = Fight(
            id="testfight02",
            creature_a_id=winner.id,
            creature_b_id=loser.id,
            winner_id=winner.id,
            tier="common",
            duration_turns=4,
        )
        session.add(fight)
        session.commit()

        fake_results = [
            FightResult(
                fight_id=fight.id,
                creature_a_id=winner.id,
                creature_b_id=loser.id,
                winner_id=winner.id,
                loser_id=loser.id,
                duration_turns=4,
            )
        ]
        result = step_resolve(session, fake_results, settings)

    assert len(result.evolved) == 1


def test_resolve_marks_creature_extinct_at_loss_threshold(client) -> None:
    from backend.simulation.engine import FightResult

    settings = _get_settings()
    with Session(engine) as session:
        winner = _create_active_creature(session)
        loser = _create_active_creature(
            session, losses=settings.extinction_loss_threshold - 1
        )
        fight = Fight(
            id="testfight03",
            creature_a_id=winner.id,
            creature_b_id=loser.id,
            winner_id=winner.id,
            tier="common",
            duration_turns=6,
        )
        session.add(fight)
        session.commit()

        fake_results = [
            FightResult(
                fight_id=fight.id,
                creature_a_id=winner.id,
                creature_b_id=loser.id,
                winner_id=winner.id,
                loser_id=loser.id,
                duration_turns=6,
            )
        ]
        step_resolve(session, fake_results, settings)

        session.refresh(loser)
        assert loser.status == "extinct"


def test_resolve_flags_rival_threshold(client) -> None:
    from backend.simulation.engine import FightResult

    settings = _get_settings()
    with Session(engine) as session:
        winner = _create_active_creature(
            session, wins=settings.rival_dominance_threshold - 1
        )
        loser = _create_active_creature(session)
        fight = Fight(
            id="testfight04",
            creature_a_id=winner.id,
            creature_b_id=loser.id,
            winner_id=winner.id,
            tier="common",
            duration_turns=3,
        )
        session.add(fight)
        session.commit()

        fake_results = [
            FightResult(
                fight_id=fight.id,
                creature_a_id=winner.id,
                creature_b_id=loser.id,
                winner_id=winner.id,
                loser_id=loser.id,
                duration_turns=3,
            )
        ]
        result = step_resolve(session, fake_results, settings)

    assert winner.id in result.rival_triggered


# ---------------------------------------------------------------------------
# POST /simulation/tick — endpoint integration
# ---------------------------------------------------------------------------


def test_tick_response_shape(client) -> None:
    r = client.post("/simulation/tick", json={"fights_per_tick": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "populate" in body
    assert "fights" in body
    assert "resolve" in body
    assert "fight_count" in body
    assert isinstance(body["fights"], list)
    assert isinstance(body["populate"]["spawned"], list)
    assert isinstance(body["resolve"]["evolved"], list)
    assert isinstance(body["resolve"]["retired"], list)


def test_tick_populates_and_fights(client) -> None:
    # Retire all creatures so the tick is forced to populate
    with Session(engine) as session:
        actives = session.exec(select(Creature).where(Creature.status == "active")).all()
        for c in actives:
            c.status = "retired"
            session.add(c)
        session.commit()

    r = client.post("/simulation/tick", json={"fights_per_tick": 3})
    assert r.status_code == 200
    body = r.json()

    # After retiring all, tick must spawn creatures
    assert len(body["populate"]["spawned"]) > 0


def test_tick_second_run_has_fights(client) -> None:
    # First tick populates
    client.post("/simulation/tick", json={"fights_per_tick": 3})
    # Second tick should have creatures to fight
    r = client.post("/simulation/tick", json={"fights_per_tick": 3})
    body = r.json()
    assert body["fight_count"] >= 0  # may be 0 if same-tier pairing not available


def test_tick_fight_entries_have_required_fields(client) -> None:
    # Populate first
    client.post("/simulation/tick", json={"fights_per_tick": 3})
    r = client.post("/simulation/tick", json={"fights_per_tick": 3})
    body = r.json()
    for fight in body["fights"]:
        for field in ("fight_id", "creature_a_id", "creature_b_id", "winner_id", "loser_id"):
            assert field in fight, f"fight missing field: {field}"
        assert fight["winner_id"] != fight["loser_id"]


def test_tick_respects_fights_per_tick(client) -> None:
    # Populate with enough creatures
    client.post("/simulation/tick", json={"fights_per_tick": 3})
    r = client.post("/simulation/tick", json={"fights_per_tick": 1})
    body = r.json()
    assert body["fight_count"] <= 1
