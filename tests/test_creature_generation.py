from __future__ import annotations

from sqlmodel import Session, select

from backend.db.models import Ability, Creature, Taunt
from backend.db.session import engine


def _generate(client, *, element="fire", archetype="berserker", tier="common", biome="volcanic"):
    budget = {"common": 80, "uncommon": 100, "rare": 125, "legendary": 160}[tier]
    r = client.post(
        "/creatures/generate",
        json={
            "seed_params": {
                "element": element,
                "archetype": archetype,
                "tier": tier,
                "biome": biome,
                "stat_budget": budget,
            }
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_generate_creature_endpoint_persists_bundle(client) -> None:
    payload = _generate(client)
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


def test_generate_creature_applies_preferred_name(client) -> None:
    preferred = "Ash Warden"
    budget = 80
    response = client.post(
        "/creatures/generate",
        json={
            "preferred_name": preferred,
            "seed_params": {
                "element": "fire",
                "archetype": "berserker",
                "tier": "common",
                "biome": "volcanic",
                "stat_budget": budget,
            },
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["name"] == preferred

    detail = client.get(f"/creatures/{payload['creature_id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == preferred


# ---------------------------------------------------------------------------
# GET /creatures
# ---------------------------------------------------------------------------


def test_list_creatures_returns_generated(client) -> None:
    _generate(client, element="fire")
    _generate(client, element="ice", archetype="sentinel", biome="tundra")

    r = client.get("/creatures")
    assert r.status_code == 200
    creatures = r.json()
    assert len(creatures) >= 2
    ids = {c["id"] for c in creatures}
    assert len(ids) == len(creatures)  # no duplicates


def test_list_creatures_filter_by_element(client) -> None:
    _generate(client, element="nature", archetype="sentinel", biome="deep forest")

    r = client.get("/creatures?element=nature")
    assert r.status_code == 200
    for c in r.json():
        assert c["element"] == "nature"


def test_list_creatures_filter_by_tier(client) -> None:
    _generate(client, tier="uncommon", element="electric", archetype="trickster", biome="storm")

    r = client.get("/creatures?tier=uncommon")
    assert r.status_code == 200
    for c in r.json():
        assert c["tier"] == "uncommon"


def test_list_creatures_pagination(client) -> None:
    for _ in range(3):
        _generate(client)

    first = client.get("/creatures?limit=2&offset=0").json()
    second = client.get("/creatures?limit=2&offset=2").json()
    assert len(first) <= 2
    assert {c["id"] for c in first}.isdisjoint({c["id"] for c in second})


def test_list_creatures_summary_shape(client) -> None:
    _generate(client)
    creatures = client.get("/creatures").json()
    c = creatures[0]
    required = ("id", "name", "tier", "element", "generation", "wins", "losses", "status", "stats")
    for field in required:
        assert field in c, f"missing field: {field}"


# ---------------------------------------------------------------------------
# GET /creatures/{id}
# ---------------------------------------------------------------------------


def test_get_creature_returns_detail(client) -> None:
    payload = _generate(client)
    creature_id = payload["creature_id"]

    r = client.get(f"/creatures/{creature_id}")
    assert r.status_code == 200
    detail = r.json()

    assert detail["id"] == creature_id
    assert len(detail["abilities"]) == payload["ability_count"]
    assert len(detail["taunts"]) == payload["taunt_count"]
    for field in ("lore", "personality", "visual_descriptor", "behavior_weights"):
        assert field in detail, f"missing field: {field}"


def test_get_creature_404_for_unknown(client) -> None:
    r = client.get("/creatures/doesnotexist")
    assert r.status_code == 404


def test_get_creature_abilities_have_required_fields(client) -> None:
    payload = _generate(client)
    detail = client.get(f"/creatures/{payload['creature_id']}").json()
    for ability in detail["abilities"]:
        for field in ("id", "name", "type", "energy_cost", "cooldown", "effect", "description"):
            assert field in ability, f"ability missing field: {field}"


def test_get_creature_taunts_have_required_fields(client) -> None:
    payload = _generate(client)
    detail = client.get(f"/creatures/{payload['creature_id']}").json()
    for taunt in detail["taunts"]:
        for field in ("id", "trigger", "text"):
            assert field in taunt, f"taunt missing field: {field}"

