"""Tests for Graph 3 (rival_graph) — node-level and integration."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from backend.db.models import Ability, Creature, Taunt
from backend.db.session import engine
from backend.graphs.nodes.gemini import MockGeminiProvider
from backend.graphs.nodes.validators import (
    node_retry_rival_patch,
    node_validate_rival,
    route_after_rival_validate,
    validate_rival_payload,
)
from backend.graphs.rival import RivalResult, run_rival_graph

PROVIDER = MockGeminiProvider()

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

_ELEMENTS = ["fire", "void", "nature", "ice", "electric"]
_ELEMENT_COUNTERS = {
    "fire": "ice",
    "ice": "electric",
    "electric": "nature",
    "nature": "void",
    "void": "fire",
}


def _make_dominant(
    creature_id: str = "dominant001",
    tier: str = "common",
    element: str = "fire",
    wins: int = 7,
) -> dict[str, Any]:
    return {
        "id": creature_id,
        "name": "Blaze Titan Surge",
        "tier": tier,
        "element": element,
        "generation": 1,
        "wins": wins,
        "stats": {"health": 25, "attack": 25, "defense": 15, "speed": 15},
        "lore": "Forged in volcanic heat, this creature has never known defeat.",
        "personality": "aggressive",
        "fighting_style": "berserker",
        "visual_descriptor": {"silhouette": "hulking", "palette": ["fire", "obsidian"]},
        "behavior_weights": {
            "aggression": 0.7,
            "caution": 0.1,
            "cunning": 0.2,
            "risk_tolerance": 0.8,
        },
    }


def _make_counter_design(dominant: dict[str, Any] | None = None) -> dict[str, Any]:
    d = dominant or _make_dominant()
    return PROVIDER.design_counter(d, [])


def _make_rival_concept(dominant: dict[str, Any] | None = None) -> dict[str, Any]:
    d = dominant or _make_dominant()
    counter = _make_counter_design(d)
    return PROVIDER.generate_rival(d, counter)


def _make_rival_taunts(dominant: dict[str, Any] | None = None) -> dict[str, list[str]]:
    d = dominant or _make_dominant()
    concept = _make_rival_concept(d)
    return PROVIDER.generate_rival_taunts(d, concept)


def _make_state(**overrides) -> dict[str, Any]:
    dominant = _make_dominant()
    counter = _make_counter_design(dominant)
    concept = _make_rival_concept(dominant)
    taunts = _make_rival_taunts(dominant)
    base: dict[str, Any] = {
        "seed_params": {},
        "dominant_creature": dominant,
        "parent_creature": None,
        "fight_history": [],
        "concept": concept,
        "stats": None,
        "abilities": None,
        "taunts": taunts,
        "visual_descriptor": None,
        "evolution_decision": None,
        "evolution_analysis": None,
        "evolution_new_ability": None,
        "evolution_updated_lore": None,
        "counter_design": counter,
        "trigger_event": "rival_spawned",
        "simulation_snapshot": None,
        "narrative_threads": None,
        "commentary_lines": None,
        "commentary_retry_count": 0,
        "validation_errors": [],
        "retry_count": 0,
        "creature_id": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# MockGeminiProvider — design_counter
# ---------------------------------------------------------------------------


class TestDesignCounter:
    def test_returns_required_keys(self):
        dominant = _make_dominant()
        result = PROVIDER.design_counter(dominant, [])
        for key in [
            "counter_element",
            "counter_archetype",
            "target_weak_stat",
            "target_strong_stat",
            "strategy",
            "boost_stat",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_counter_element_differs_from_dominant(self):
        for element in _ELEMENTS:
            dominant = _make_dominant(element=element)
            result = PROVIDER.design_counter(dominant, [])
            assert result["counter_element"] != element

    def test_counter_follows_element_cycle(self):
        for element, expected_counter in _ELEMENT_COUNTERS.items():
            dominant = _make_dominant(element=element)
            result = PROVIDER.design_counter(dominant, [])
            assert result["counter_element"] == expected_counter

    def test_boost_stat_is_dominant_weak_stat(self):
        dominant = _make_dominant()
        dominant["stats"] = {"health": 10, "attack": 25, "defense": 20, "speed": 25}
        result = PROVIDER.design_counter(dominant, [])
        assert result["boost_stat"] == "health"
        assert result["target_weak_stat"] == "health"

    def test_deterministic_with_same_id(self):
        dominant = _make_dominant()
        r1 = PROVIDER.design_counter(dominant, [])
        r2 = PROVIDER.design_counter(dominant, [])
        assert r1 == r2


# ---------------------------------------------------------------------------
# MockGeminiProvider — generate_rival
# ---------------------------------------------------------------------------


class TestGenerateRival:
    def test_returns_required_keys(self):
        dominant = _make_dominant()
        counter = _make_counter_design(dominant)
        result = PROVIDER.generate_rival(dominant, counter)
        for key in [
            "name",
            "lore",
            "personality",
            "fighting_style",
            "visual_descriptor",
            "behavior_weights",
            "counter_element",
            "counter_archetype",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_name_references_dominant(self):
        dominant = _make_dominant()
        counter = _make_counter_design(dominant)
        result = PROVIDER.generate_rival(dominant, counter)
        assert dominant["name"] in result["name"] or dominant["name"] in result["lore"]

    def test_counter_element_matches_design(self):
        dominant = _make_dominant(element="fire")
        counter = _make_counter_design(dominant)
        result = PROVIDER.generate_rival(dominant, counter)
        assert result["counter_element"] == "ice"


# ---------------------------------------------------------------------------
# MockGeminiProvider — generate_rival_taunts
# ---------------------------------------------------------------------------


class TestGenerateRivalTaunts:
    def test_returns_dict_of_lists(self):
        dominant = _make_dominant()
        concept = _make_rival_concept(dominant)
        result = PROVIDER.generate_rival_taunts(dominant, concept)
        assert isinstance(result, dict)
        for _trigger, lines in result.items():
            assert isinstance(lines, list)
            assert all(isinstance(line, str) for line in lines)

    def test_taunts_reference_dominant_name(self):
        dominant = _make_dominant()
        concept = _make_rival_concept(dominant)
        result = PROVIDER.generate_rival_taunts(dominant, concept)
        all_text = " ".join(line for lines in result.values() for line in lines)
        assert dominant["name"] in all_text

    def test_has_multiple_triggers(self):
        dominant = _make_dominant()
        concept = _make_rival_concept(dominant)
        result = PROVIDER.generate_rival_taunts(dominant, concept)
        assert len(result) >= 3


# ---------------------------------------------------------------------------
# node_validate_rival
# ---------------------------------------------------------------------------


class TestNodeValidateRival:
    def test_valid_state_returns_no_errors(self):
        state = _make_state()
        result = node_validate_rival(state)
        assert result["validation_errors"] == []

    def test_missing_dominant_creature_errors(self):
        state = _make_state(dominant_creature=None)
        result = node_validate_rival(state)
        assert result["validation_errors"]

    def test_missing_concept_errors(self):
        state = _make_state(concept=None)
        result = node_validate_rival(state)
        assert result["validation_errors"]

    def test_missing_taunts_errors(self):
        state = _make_state(taunts=None)
        result = node_validate_rival(state)
        assert result["validation_errors"]

    def test_same_element_as_dominant_errors(self):
        dominant = _make_dominant(element="fire")
        counter = _make_counter_design(dominant)
        concept = _make_rival_concept(dominant)
        concept["counter_element"] = "fire"  # Force same element
        taunts = _make_rival_taunts(dominant)
        state = _make_state(
            dominant_creature=dominant,
            counter_design=counter,
            concept=concept,
            taunts=taunts,
        )
        result = node_validate_rival(state)
        assert any("counter_element" in e for e in result["validation_errors"])

    def test_taunts_without_dominant_name_errors(self):
        dominant = _make_dominant()
        counter = _make_counter_design(dominant)
        concept = _make_rival_concept(dominant)
        bad_taunts = {"intro": ["Generic taunt line with no name reference."]}
        state = _make_state(
            dominant_creature=dominant,
            counter_design=counter,
            concept=concept,
            taunts=bad_taunts,
        )
        result = node_validate_rival(state)
        assert any("taunt" in e.lower() for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# node_retry_rival_patch
# ---------------------------------------------------------------------------


class TestNodeRetryRivalPatch:
    def test_increments_retry_count(self):
        state = _make_state(retry_count=0)
        result = node_retry_rival_patch(state)
        assert result["retry_count"] == 1

    def test_clears_concept_and_taunts(self):
        state = _make_state()
        result = node_retry_rival_patch(state)
        assert result["concept"] is None
        assert result["taunts"] is None

    def test_clears_validation_errors(self):
        state = _make_state(validation_errors=["some error"])
        result = node_retry_rival_patch(state)
        assert result["validation_errors"] == []


# ---------------------------------------------------------------------------
# route_after_rival_validate
# ---------------------------------------------------------------------------


class TestRouteAfterRivalValidate:
    def test_routes_to_write_rival_when_valid(self):
        route = route_after_rival_validate(max_retries=2)
        state = _make_state(validation_errors=[])
        assert route(state) == "write_rival"

    def test_routes_to_retry_when_errors_and_under_limit(self):
        route = route_after_rival_validate(max_retries=2)
        state = _make_state(validation_errors=["bad"], retry_count=0)
        assert route(state) == "retry_rival"

    def test_routes_to_failed_when_max_retries_hit(self):
        route = route_after_rival_validate(max_retries=2)
        state = _make_state(validation_errors=["bad"], retry_count=2)
        assert route(state) == "failed"


# ---------------------------------------------------------------------------
# validate_rival_payload — edge cases
# ---------------------------------------------------------------------------


class TestValidateRivalPayload:
    def test_empty_taunts_dict_errors(self):
        dominant = _make_dominant()
        counter = _make_counter_design(dominant)
        concept = _make_rival_concept(dominant)
        errors = validate_rival_payload(
            dominant_creature=dominant,
            counter_design=counter,
            concept=concept,
            taunts={},
        )
        assert any("taunt" in e.lower() for e in errors)

    def test_valid_payload_no_errors(self):
        dominant = _make_dominant()
        counter = _make_counter_design(dominant)
        concept = _make_rival_concept(dominant)
        taunts = _make_rival_taunts(dominant)
        errors = validate_rival_payload(
            dominant_creature=dominant,
            counter_design=counter,
            concept=concept,
            taunts=taunts,
        )
        assert errors == []


# ---------------------------------------------------------------------------
# run_rival_graph — integration
# ---------------------------------------------------------------------------


class TestRunRivalGraph:
    def test_produces_rival_with_rival_of_set(self):
        dominant = _make_dominant(wins=7)
        with Session(engine) as session:
            # Create the dominant creature in DB first
            dominant_obj = Creature(
                id=dominant["id"],
                name=dominant["name"],
                tier=dominant["tier"],
                element=dominant["element"],
                stats=dominant["stats"],
                lore=dominant["lore"],
                personality=dominant["personality"],
                fighting_style=dominant["fighting_style"],
                visual_descriptor=dominant["visual_descriptor"],
                behavior_weights=dominant["behavior_weights"],
                wins=dominant["wins"],
            )
            session.add(dominant_obj)
            session.commit()

            result = run_rival_graph(session, dominant_creature=dominant, provider=PROVIDER)

        assert isinstance(result, RivalResult)
        assert result.rival_id
        assert result.dominant_id == dominant["id"]
        assert result.counter_element == _ELEMENT_COUNTERS["fire"]
        assert result.retry_count == 0

    def test_rival_persisted_in_db(self):
        dominant = _make_dominant(creature_id="dominant002", element="nature", wins=7)
        with Session(engine) as session:
            dominant_obj = Creature(
                id=dominant["id"],
                name=dominant["name"],
                tier=dominant["tier"],
                element=dominant["element"],
                stats=dominant["stats"],
                lore=dominant["lore"],
                personality=dominant["personality"],
                fighting_style=dominant["fighting_style"],
                visual_descriptor=dominant["visual_descriptor"],
                behavior_weights=dominant["behavior_weights"],
                wins=dominant["wins"],
            )
            session.add(dominant_obj)
            session.commit()

            result = run_rival_graph(session, dominant_creature=dominant, provider=PROVIDER)

            rival = session.get(Creature, result.rival_id)
            assert rival is not None
            assert rival.rival_of == dominant["id"]
            assert rival.element == _ELEMENT_COUNTERS["nature"]

    def test_rival_has_abilities(self):
        dominant = _make_dominant(creature_id="dominant003", element="void", wins=7)
        with Session(engine) as session:
            dominant_obj = Creature(
                id=dominant["id"],
                name=dominant["name"],
                tier=dominant["tier"],
                element=dominant["element"],
                stats=dominant["stats"],
                lore=dominant["lore"],
                personality=dominant["personality"],
                fighting_style=dominant["fighting_style"],
                visual_descriptor=dominant["visual_descriptor"],
                behavior_weights=dominant["behavior_weights"],
                wins=dominant["wins"],
            )
            session.add(dominant_obj)
            session.commit()

            result = run_rival_graph(session, dominant_creature=dominant, provider=PROVIDER)

            abilities = session.exec(
                select(Ability).where(Ability.creature_id == result.rival_id)
            ).all()
            assert len(abilities) >= 1

    def test_rival_has_taunts(self):
        dominant = _make_dominant(creature_id="dominant004", element="electric", wins=7)
        with Session(engine) as session:
            dominant_obj = Creature(
                id=dominant["id"],
                name=dominant["name"],
                tier=dominant["tier"],
                element=dominant["element"],
                stats=dominant["stats"],
                lore=dominant["lore"],
                personality=dominant["personality"],
                fighting_style=dominant["fighting_style"],
                visual_descriptor=dominant["visual_descriptor"],
                behavior_weights=dominant["behavior_weights"],
                wins=dominant["wins"],
            )
            session.add(dominant_obj)
            session.commit()

            result = run_rival_graph(session, dominant_creature=dominant, provider=PROVIDER)

            taunts = session.exec(
                select(Taunt).where(Taunt.creature_id == result.rival_id)
            ).all()
            assert len(taunts) >= 1


# ---------------------------------------------------------------------------
# POST /creatures/{id}/spawn-rival — endpoint tests
# ---------------------------------------------------------------------------


class TestSpawnRivalEndpoint:
    def test_404_for_unknown_creature(self, client):
        response = client.post("/creatures/nonexistent/spawn-rival")
        assert response.status_code == 404

    def test_409_when_wins_below_threshold(self, client):
        # Create creature with 0 wins
        gen_resp = client.post(
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
        assert gen_resp.status_code == 201
        creature_id = gen_resp.json()["creature_id"]

        response = client.post(f"/creatures/{creature_id}/spawn-rival")
        assert response.status_code == 409
        assert "wins" in response.json()["detail"].lower()

    def test_201_when_wins_at_threshold(self, client):
        from sqlmodel import Session

        from backend.db.models import Creature
        from backend.db.session import engine

        # Generate creature, then forcibly set wins to 7
        gen_resp = client.post(
            "/creatures/generate",
            json={
                "seed_params": {
                    "element": "ice",
                    "archetype": "sentinel",
                    "tier": "common",
                    "biome": "tundra",
                    "stat_budget": 80,
                }
            },
        )
        assert gen_resp.status_code == 201
        creature_id = gen_resp.json()["creature_id"]

        with Session(engine) as session:
            creature = session.get(Creature, creature_id)
            creature.wins = 7
            session.add(creature)
            session.commit()

        response = client.post(f"/creatures/{creature_id}/spawn-rival")
        assert response.status_code == 201
        data = response.json()
        assert data["dominant_id"] == creature_id
        assert data["rival_id"]
        assert data["counter_element"] == "electric"
