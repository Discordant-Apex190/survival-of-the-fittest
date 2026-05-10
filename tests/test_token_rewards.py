from __future__ import annotations

from sqlmodel import Session

from backend.graphs.creature_factory import run_creature_factory_graph
from backend.simulation.engine import apply_token_rewards, step_fight

_SEED_PARAMS = {
    "element": "fire",
    "archetype": "berserker",
    "tier": "common",
    "biome": "volcanic",
    "stat_budget": 80,
}


def _generate_creature(session: Session) -> str:
    return run_creature_factory_graph(session, seed_params=_SEED_PARAMS).creature_id


def test_apply_token_rewards_broadcasts_expected_payload(monkeypatch) -> None:
    captured: list[dict] = []

    def _capture(payload: dict) -> None:
        captured.append(payload)

    monkeypatch.setattr("backend.simulation.engine.manager.broadcast_sync", _capture)

    apply_token_rewards(fight_id="fight-123", amount=77)

    assert captured == [
        {
            "type": "token_earned",
            "fight_id": "fight-123",
            "amount": 77,
            "reason": "fight_completion",
        }
    ]


def test_step_fight_broadcasts_token_earned_after_fight_end(
    db_session: Session,
    monkeypatch,
) -> None:
    a_id = _generate_creature(db_session)
    b_id = _generate_creature(db_session)
    captured: list[dict] = []

    def _capture(payload: dict) -> None:
        captured.append(payload)

    monkeypatch.setattr("backend.simulation.engine.manager.broadcast_sync", _capture)

    result = step_fight(db_session, (a_id, b_id), seed="token-reward-seed")

    token_events = [e for e in captured if e.get("type") == "token_earned"]
    fight_end_events = [e for e in captured if e.get("type") == "fight_end"]

    assert len(fight_end_events) == 1
    assert len(token_events) == 1
    assert token_events[0]["fight_id"] == result.fight_id
    assert token_events[0]["amount"] == 50

    fight_end_index = next(i for i, e in enumerate(captured) if e.get("type") == "fight_end")
    token_index = next(i for i, e in enumerate(captured) if e.get("type") == "token_earned")
    assert token_index > fight_end_index
