"""Tests for Graph 2 (evolution) — node-level and endpoint-level."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from backend.db.models import Ability, Creature, Evolution
from backend.db.session import engine
from backend.graphs.nodes.gemini import MockGeminiProvider, node_analyse_history
from backend.graphs.nodes.validators import (
    EVOLUTION_BONUS,
    TIER_BUDGETS,
    node_retry_evolution_patch,
    node_validate_evolution_budget,
    route_after_evolution_validate,
)

PROVIDER = MockGeminiProvider()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STAT_NAMES = ["health", "attack", "defense", "speed"]


def _make_parent(
    creature_id: str = "parent123",
    tier: str = "common",
    element: str = "fire",
    generation: int = 1,
    wins: int = 3,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    if stats is None:
        budget = TIER_BUDGETS[tier][0]
        per = budget // 4
        remainder = budget - per * 4
        stats = {"health": per + remainder, "attack": per, "defense": per, "speed": per}
    return {
        "id": creature_id,
        "name": "Flame Berserker Fang",
        "tier": tier,
        "element": element,
        "generation": generation,
        "stats": stats,
        "lore": "Forged in volcanic heat.",
        "personality": "aggressive",
        "fighting_style": "rushdown",
        "visual_descriptor": {"silhouette": "lean", "palette": ["fire", "obsidian"]},
        "behavior_weights": {"attack": 0.6, "defend": 0.2, "ability": 0.2},
        "wins": wins,
    }


def _make_state(parent: dict[str, Any] | None = None, **overrides) -> dict[str, Any]:
    p = parent or _make_parent()
    budget = TIER_BUDGETS[p["tier"]][0]
    base: dict[str, Any] = {
        "parent_creature": p,
        "fight_history": [],
        "evolution_analysis": None,
        "evolution_decision": None,
        "evolution_new_ability": None,
        "evolution_updated_lore": None,
        "validation_errors": [],
        "retry_count": 0,
        "creature_id": None,
        "_budget": budget,
    }
    base.update(overrides)
    return base


def _valid_decision(parent: dict[str, Any], boost: int = 3) -> dict[str, Any]:
    """Returns a decision with a single safe stat boost."""
    stat = "health"
    return {
        "stat_boosts": {stat: boost},
        "new_ability_slot": False,
        "reasoning": "testing",
    }


# ---------------------------------------------------------------------------
# node_analyse_history
# ---------------------------------------------------------------------------


def test_analyse_history_empty_fight_list() -> None:
    state = _make_state(fight_history=[])
    result = node_analyse_history(state)
    analysis = result["evolution_analysis"]
    assert analysis["win_rate"] == 0.0
    assert analysis["weaknesses"] == []
    assert analysis["avg_turns"] == 0.0


def test_analyse_history_computes_win_rate() -> None:
    fights = [
        {"won": True, "opponent_element": "ice", "abilities_used": ["Ember Arc 1"], "turns": 5},
        {"won": True, "opponent_element": "void", "abilities_used": [], "turns": 3},
        {"won": False, "opponent_element": "nature", "abilities_used": [], "turns": 7},
    ]
    state = _make_state(fight_history=fights)
    result = node_analyse_history(state)
    analysis = result["evolution_analysis"]
    assert abs(analysis["win_rate"] - (2 / 3)) < 0.01
    assert "nature" in analysis["weaknesses"]
    assert "ice" not in analysis["weaknesses"]


def test_analyse_history_avg_turns() -> None:
    fights = [
        {"won": True, "turns": 4},
        {"won": False, "turns": 8},
    ]
    state = _make_state(fight_history=fights)
    analysis = node_analyse_history(state)["evolution_analysis"]
    assert analysis["avg_turns"] == 6.0


# ---------------------------------------------------------------------------
# MockGeminiProvider.decide_evolution
# ---------------------------------------------------------------------------


def test_decide_evolution_returns_required_keys() -> None:
    parent = _make_parent()
    analysis = {"weaknesses": [], "win_rate": 1.0, "unused_abilities": [], "avg_turns": 3.0}
    decision = PROVIDER.decide_evolution(parent, analysis)
    assert "stat_boosts" in decision
    assert "new_ability_slot" in decision
    assert "reasoning" in decision
    assert isinstance(decision["stat_boosts"], dict)
    assert isinstance(decision["new_ability_slot"], bool)


def test_decide_evolution_stat_boosts_are_positive() -> None:
    parent = _make_parent()
    analysis = {"weaknesses": ["ice"], "win_rate": 0.6, "unused_abilities": [], "avg_turns": 5.0}
    decision = PROVIDER.decide_evolution(parent, analysis)
    for val in decision["stat_boosts"].values():
        assert val > 0


def test_decide_evolution_deterministic() -> None:
    parent = _make_parent()
    analysis = {"weaknesses": [], "win_rate": 1.0, "unused_abilities": [], "avg_turns": 4.0}
    d1 = PROVIDER.decide_evolution(parent, analysis)
    d2 = PROVIDER.decide_evolution(parent, analysis)
    assert d1 == d2


# ---------------------------------------------------------------------------
# MockGeminiProvider.generate_evolution_ability
# ---------------------------------------------------------------------------


def test_generate_evolution_ability_shape() -> None:
    parent = _make_parent()
    decision = _valid_decision(parent)
    ability = PROVIDER.generate_evolution_ability(parent, decision)
    for field in ("name", "type", "energy_cost", "cooldown", "effect", "description"):
        assert field in ability, f"missing ability field: {field}"
    assert ability["type"] == parent["element"]
    assert ability["energy_cost"] > 0


# ---------------------------------------------------------------------------
# MockGeminiProvider.update_lore
# ---------------------------------------------------------------------------


def test_update_lore_appends_reasoning() -> None:
    parent = _make_parent()
    decision = {
        "reasoning": "adapted to ice weaknesses",
        "stat_boosts": {},
        "new_ability_slot": False,
    }
    new_lore = PROVIDER.update_lore(parent, decision)
    assert parent["lore"] in new_lore
    assert "adapted to ice weaknesses" in new_lore
    assert len(new_lore) > len(parent["lore"])


# ---------------------------------------------------------------------------
# node_validate_evolution_budget
# ---------------------------------------------------------------------------


def test_validate_evolution_budget_passes_small_boost() -> None:
    parent = _make_parent(tier="common")
    decision = _valid_decision(parent, boost=3)
    state = _make_state(parent=parent, evolution_decision=decision)
    result = node_validate_evolution_budget(state)
    assert result["validation_errors"] == []


def test_validate_evolution_budget_fails_over_ceiling() -> None:
    parent = _make_parent(tier="common")  # budget=80, ceiling=90
    # boost by 11 — total becomes 91 > 90
    decision = {"stat_boosts": {"health": 11}, "new_ability_slot": False, "reasoning": ""}
    state = _make_state(parent=parent, evolution_decision=decision)
    result = node_validate_evolution_budget(state)
    assert any("exceeds budget ceiling" in e for e in result["validation_errors"])


def test_validate_evolution_budget_fails_single_stat_cap() -> None:
    parent = _make_parent(
        tier="common",
        stats={"health": 25, "attack": 20, "defense": 20, "speed": 15},
    )
    # boost health by 1 makes it 26 > common max_single (25)
    decision = {"stat_boosts": {"health": 1}, "new_ability_slot": False, "reasoning": ""}
    state = _make_state(parent=parent, evolution_decision=decision)
    result = node_validate_evolution_budget(state)
    assert any("exceeds tier max" in e for e in result["validation_errors"])


def test_validate_evolution_budget_bonus_boundary() -> None:
    # legendary: budget=160, max_single=50, ceiling=170
    # All stats start at 40 → boost health by 10 → 50 (= max_single), sum=170 (= ceiling)
    parent = _make_parent(
        tier="legendary",
        stats={"health": 40, "attack": 40, "defense": 40, "speed": 40},
    )
    decision = {
        "stat_boosts": {"health": EVOLUTION_BONUS},
        "new_ability_slot": False,
        "reasoning": "",
    }
    state = _make_state(parent=parent, evolution_decision=decision)
    result = node_validate_evolution_budget(state)
    assert result["validation_errors"] == []


# ---------------------------------------------------------------------------
# node_retry_evolution_patch
# ---------------------------------------------------------------------------


def test_retry_evolution_patch_increments_count() -> None:
    state = _make_state(retry_count=1, evolution_decision={"foo": "bar"}, validation_errors=["err"])
    result = node_retry_evolution_patch(state)
    assert result["retry_count"] == 2
    assert result["evolution_decision"] is None
    assert result["validation_errors"] == []


# ---------------------------------------------------------------------------
# route_after_evolution_validate
# ---------------------------------------------------------------------------


def test_route_passes_when_no_errors() -> None:
    router = route_after_evolution_validate(max_retries=3)
    state = _make_state(validation_errors=[], retry_count=0)
    assert router(state) == "write_evolution"


def test_route_retries_when_errors_and_attempts_remain() -> None:
    router = route_after_evolution_validate(max_retries=3)
    state = _make_state(validation_errors=["boom"], retry_count=1)
    assert router(state) == "retry_evolution"


def test_route_fails_when_retries_exhausted() -> None:
    router = route_after_evolution_validate(max_retries=3)
    state = _make_state(validation_errors=["boom"], retry_count=3)
    assert router(state) == "failed"


# ---------------------------------------------------------------------------
# POST /creatures/{id}/evolve — endpoint integration
# ---------------------------------------------------------------------------


def _generate_creature(client, *, tier: str = "common") -> dict:
    budget = {"common": 80, "uncommon": 100, "rare": 125, "legendary": 160}[tier]
    r = client.post(
        "/creatures/generate",
        json={
            "seed_params": {
                "element": "fire",
                "archetype": "berserker",
                "tier": tier,
                "biome": "volcanic",
                "stat_budget": budget,
            }
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _set_wins(creature_id: str, wins: int) -> None:
    with Session(engine) as session:
        c = session.get(Creature, creature_id)
        c.wins = wins
        session.add(c)
        session.commit()


def test_evolve_requires_win_threshold(client) -> None:
    payload = _generate_creature(client)
    _set_wins(payload["creature_id"], 0)
    r = client.post(f"/creatures/{payload['creature_id']}/evolve")
    assert r.status_code == 409
    assert "wins" in r.json()["detail"]


def test_evolve_404_for_unknown(client) -> None:
    r = client.post("/creatures/doesnotexist/evolve")
    assert r.status_code == 404


def test_evolve_creates_child_creature(client) -> None:
    payload = _generate_creature(client)
    parent_id = payload["creature_id"]
    _set_wins(parent_id, 3)

    r = client.post(f"/creatures/{parent_id}/evolve")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["parent_id"] == parent_id
    assert body["generation"] == 2
    assert isinstance(body["stat_boosts"], dict)
    assert isinstance(body["new_ability"], bool)
    assert body["graph_state"]["trigger_event"] == "evolution"
    assert body["child_id"] == body["graph_state"]["creature_id"]


def test_evolve_retires_parent(client) -> None:
    payload = _generate_creature(client)
    parent_id = payload["creature_id"]
    _set_wins(parent_id, 3)

    client.post(f"/creatures/{parent_id}/evolve")

    with Session(engine) as session:
        parent = session.get(Creature, parent_id)
        assert parent.status == "retired"


def test_evolve_child_persisted_in_db(client) -> None:
    payload = _generate_creature(client)
    parent_id = payload["creature_id"]
    _set_wins(parent_id, 3)

    r = client.post(f"/creatures/{parent_id}/evolve")
    child_id = r.json()["child_id"]

    with Session(engine) as session:
        child = session.get(Creature, child_id)
        assert child is not None
        assert child.parent_id == parent_id
        assert child.generation == 2
        assert child.tier == "common"

        parent_ability_count = len(
            session.exec(select(Ability).where(Ability.creature_id == parent_id)).all()
        )
        child_abilities = session.exec(select(Ability).where(Ability.creature_id == child_id)).all()
        # Child should have at least as many abilities as parent (plus possibly one new)
        assert len(child_abilities) >= parent_ability_count


def test_evolve_creates_evolution_record(client) -> None:
    payload = _generate_creature(client)
    parent_id = payload["creature_id"]
    _set_wins(parent_id, 3)

    r = client.post(f"/creatures/{parent_id}/evolve")
    child_id = r.json()["child_id"]

    with Session(engine) as session:
        evolutions = session.exec(
            select(Evolution).where(Evolution.parent_id == parent_id)
        ).all()
        assert len(evolutions) == 1
        assert evolutions[0].child_id == child_id
        assert evolutions[0].trigger == "win_threshold"


def test_evolve_rejects_retired_creature(client) -> None:
    payload = _generate_creature(client)
    parent_id = payload["creature_id"]
    _set_wins(parent_id, 3)

    # First evolution retires the parent
    client.post(f"/creatures/{parent_id}/evolve")

    # Attempting again on the now-retired parent should 409
    r = client.post(f"/creatures/{parent_id}/evolve")
    assert r.status_code == 409
    assert "retired" in r.json()["detail"]
