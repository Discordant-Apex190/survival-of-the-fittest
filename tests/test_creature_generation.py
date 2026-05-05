from __future__ import annotations

from sqlmodel import Session, select

from backend.db.models import Ability, Creature, Taunt
from backend.db.session import engine


def test_generate_creature_endpoint_persists_bundle(client) -> None:
    response = client.post(
        "/creatures/generate",
        json={
            "seed_params": {
                "element": "fire",
                "archetype": "berserker",
                "tier": "common",
                "biome": "volcanic",
                "stat_budget": 80,
            }
        },
    )

    assert response.status_code == 201
    payload = response.json()
    creature_id = payload["creature_id"]

    assert payload["tier"] == "common"
    assert payload["element"] == "fire"
    assert payload["ability_count"] >= 1
    assert payload["taunt_count"] >= 1
    assert payload["graph_state"]["trigger_event"] == "creature_factory"
    assert payload["graph_state"]["creature_id"] == creature_id
    assert payload["graph_state"]["concept"] is not None
    assert payload["graph_state"]["stats"] is not None
    assert payload["graph_state"]["abilities"] is not None
    assert payload["graph_state"]["taunts"] is not None

    with Session(engine) as session:
        creature = session.get(Creature, creature_id)
        assert creature is not None
        assert creature.tier == "common"

        abilities = session.exec(select(Ability).where(Ability.creature_id == creature_id)).all()
        taunts = session.exec(select(Taunt).where(Taunt.creature_id == creature_id)).all()
        assert len(abilities) == payload["ability_count"]
        assert len(taunts) == payload["taunt_count"]


def test_generate_creature_endpoint_rejects_invalid_budget(client) -> None:
    response = client.post(
        "/creatures/generate",
        json={
            "seed_params": {
                "element": "void",
                "archetype": "trickster",
                "tier": "common",
                "biome": "rift",
                "stat_budget": 81,
            }
        },
    )

    assert response.status_code == 422
