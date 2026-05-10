from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import Random
from threading import Lock
from time import monotonic, sleep
from typing import Any, Protocol

import httpx
import orjson
from loguru import logger

from backend.core.config import get_settings

# Imported here to cap mock evolution boosts — no circular dep (validators doesn't import gemini)
_TIER_MAX_SINGLE: dict[str, int] = {
    "common": 25,
    "uncommon": 30,
    "rare": 38,
    "legendary": 50,
}


@dataclass(slots=True)
class GeneratedStats:
    stats: dict[str, int]
    abilities: list[dict[str, Any]]


class GeminiProvider(Protocol):
    def generate_concept(self, seed_params: dict[str, Any]) -> dict[str, Any]: ...

    def generate_stats(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> GeneratedStats: ...

    def generate_taunts(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> dict[str, list[str]]: ...

    def decide_evolution(
        self, parent_creature: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]: ...

    def generate_evolution_ability(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> dict[str, Any]: ...

    def update_lore(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> str: ...

    def design_counter(
        self,
        dominant_creature: dict[str, Any],
        fight_history: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    def generate_rival(
        self,
        dominant_creature: dict[str, Any],
        counter_design: dict[str, Any],
    ) -> dict[str, Any]: ...

    def generate_rival_taunts(
        self,
        dominant_creature: dict[str, Any],
        rival_concept: dict[str, Any],
    ) -> dict[str, list[str]]: ...

    def gather_context(
        self,
        trigger_event: str,
        simulation_snapshot: dict[str, Any],
    ) -> dict[str, Any]: ...

    def identify_narrative_threads(
        self,
        context: dict[str, Any],
    ) -> list[str]: ...

    def generate_commentary(
        self,
        trigger_event: str,
        narrative_threads: list[str],
        simulation_snapshot: dict[str, Any],
    ) -> list[str]: ...


class RealGeminiProvider:
    """HTTP adapter for Gemini API with structured JSON prompts."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        min_interval_s: float = 0.5,
        max_retries: int = 3,
        base_backoff_s: float = 0.6,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.base_backoff_s = base_backoff_s
        self._lock = Lock()
        self._next_allowed_at = 0.0
        self._fallback = MockGeminiProvider()

    def _respect_rate_limit(self) -> None:
        with self._lock:
            now = monotonic()
            wait_s = max(0.0, self._next_allowed_at - now)
            self._next_allowed_at = max(self._next_allowed_at, now) + self.min_interval_s
        if wait_s > 0:
            sleep(wait_s)

    def _retry_wait(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        # Lightweight jitter: 85%-115% around exponential backoff.
        jitter = Random(f"{self.model}:{attempt}:jitter").uniform(0.85, 1.15)
        return self.base_backoff_s * (2**attempt) * jitter

    def _call_model(self, prompt: str, *, json_mode: bool) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
        }
        if json_mode:
            payload["generationConfig"] = {"responseMimeType": "application/json"}

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=45.0) as client:
            for attempt in range(self.max_retries + 1):
                self._respect_rate_limit()
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 429 and attempt < self.max_retries:
                    wait_s = self._retry_wait(attempt, resp.headers.get("Retry-After"))
                    logger.bind(
                        stage="gemini_retry",
                        model=self.model,
                        attempt=attempt + 1,
                        wait_s=round(wait_s, 2),
                    ).warning("gemini | rate limited, retrying")
                    sleep(wait_s)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break

        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError("Gemini returned empty content parts")
        text = parts[0].get("text", "")
        if not text:
            raise ValueError("Gemini returned empty text")
        return text

    def _call_json(self, task: str, prompt: str) -> Any:
        try:
            text = self._call_model(prompt, json_mode=True)
            return orjson.loads(text)
        except Exception as exc:  # noqa: BLE001
            logger.bind(stage="gemini_json_fallback", task=task, error=str(exc)).warning(
                "gemini | json call failed, using mock fallback"
            )
            raise

    def generate_concept(self, seed_params: dict[str, Any]) -> dict[str, Any]:
        from backend.graphs.nodes.concept_generator import generate_concept_local
        rng = Random(":".join([
            str(seed_params.get("element", "")),
            str(seed_params.get("archetype", "")),
            str(seed_params.get("tier", "")),
            str(seed_params.get("biome", "")),
        ]))
        return generate_concept_local(seed_params, rng)

    def generate_stats(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> GeneratedStats:
        from backend.graphs.nodes.stat_generator import generate_stats_local
        rng = Random(":".join([
            str(seed_params.get("element", "")),
            str(seed_params.get("archetype", "")),
            str(seed_params.get("tier", "")),
            str(seed_params.get("biome", "")),
        ]))
        return generate_stats_local(
            archetype=seed_params.get("archetype", "berserker"),
            element=seed_params.get("element", "fire"),
            tier=seed_params.get("tier", "common"),
            rng=rng,
        )

    def generate_taunts(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> dict[str, list[str]]:
        from backend.graphs.nodes.concept_generator import generate_taunts_local
        rng = Random(":".join([
            str(seed_params.get("element", "")),
            str(seed_params.get("archetype", "")),
            str(concept.get("name", "")),
        ]))
        return generate_taunts_local(seed_params, concept, rng)

    def decide_evolution(
        self, parent_creature: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]:
        from backend.fight.genetic import genetic_decide_evolution
        return genetic_decide_evolution(parent_creature, analysis)

    def generate_evolution_ability(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> dict[str, Any]:
        from backend.graphs.nodes.stat_generator import generate_evolution_ability_local
        rng = Random(
            f"{parent_creature.get('id', '')}:new_ability:{parent_creature.get('generation', 0)}"
        )
        return generate_evolution_ability_local(parent_creature, rng)

    def update_lore(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> str:
        from backend.graphs.nodes.concept_generator import update_lore_local
        rng = Random(f"{parent_creature.get('id', '')}:lore:{parent_creature.get('generation', 0)}")
        return update_lore_local(parent_creature, evolution_decision, rng)

    def design_counter(
        self,
        dominant_creature: dict[str, Any],
        fight_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from backend.graphs.nodes.counter_logic import design_counter_local
        return design_counter_local(dominant_creature, fight_history)

    def generate_rival(
        self,
        dominant_creature: dict[str, Any],
        counter_design: dict[str, Any],
    ) -> dict[str, Any]:
        from backend.graphs.nodes.counter_logic import generate_rival_local
        return generate_rival_local(dominant_creature, counter_design)

    def generate_rival_taunts(
        self,
        dominant_creature: dict[str, Any],
        rival_concept: dict[str, Any],
    ) -> dict[str, list[str]]:
        from backend.graphs.nodes.concept_generator import generate_rival_taunts_local
        rng = Random(f"{dominant_creature.get('id', '')}:rival_taunts")
        return generate_rival_taunts_local(dominant_creature, rival_concept, rng)

    def gather_context(
        self,
        trigger_event: str,
        simulation_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return self._fallback.gather_context(trigger_event, simulation_snapshot)

    def identify_narrative_threads(
        self,
        context: dict[str, Any],
    ) -> list[str]:
        from backend.graphs.nodes.concept_generator import identify_narrative_threads_local
        return identify_narrative_threads_local(context)

    def generate_commentary(
        self,
        trigger_event: str,
        narrative_threads: list[str],
        simulation_snapshot: dict[str, Any],
    ) -> list[str]:
        from backend.graphs.nodes.concept_generator import generate_commentary_local
        rng = Random(
            f"{trigger_event}:{len(narrative_threads)}:"
            f"{simulation_snapshot.get('total_fights', 0)}"
        )
        return generate_commentary_local(trigger_event, narrative_threads, simulation_snapshot, rng)


class MockGeminiProvider:
    """Deterministic local provider used until real Gemini integration is enabled."""

    def _rng(self, seed_params: dict[str, Any]) -> Random:
        seed = ":".join(
            [
                str(seed_params["element"]),
                str(seed_params["archetype"]),
                str(seed_params["tier"]),
                str(seed_params["biome"]),
            ]
        )
        return Random(seed)

    def generate_concept(self, seed_params: dict[str, Any]) -> dict[str, Any]:
        from backend.graphs.nodes.concept_generator import generate_concept_local
        return generate_concept_local(seed_params, self._rng(seed_params))

    def generate_stats(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> GeneratedStats:
        from backend.graphs.nodes.stat_generator import generate_stats_local
        rng = self._rng(seed_params)
        return generate_stats_local(
            archetype=seed_params.get("archetype", "berserker"),
            element=seed_params.get("element", "fire"),
            tier=seed_params.get("tier", "common"),
            rng=rng,
        )

    def generate_taunts(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> dict[str, list[str]]:
        from backend.graphs.nodes.concept_generator import generate_taunts_local
        rng = Random(":".join([
            str(seed_params.get("element", "")),
            str(seed_params.get("archetype", "")),
            str(concept.get("name", "")),
        ]))
        return generate_taunts_local(seed_params, concept, rng)

    def decide_evolution(
        self, parent_creature: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]:
        from backend.fight.genetic import genetic_decide_evolution
        return genetic_decide_evolution(parent_creature, analysis)

    def generate_evolution_ability(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> dict[str, Any]:
        from backend.graphs.nodes.stat_generator import generate_evolution_ability_local
        rng = Random(
            f"{parent_creature.get('id', '')}:new_ability:{parent_creature.get('generation', 0)}"
        )
        return generate_evolution_ability_local(parent_creature, rng)

    def update_lore(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> str:
        from backend.graphs.nodes.concept_generator import update_lore_local
        rng = Random(f"{parent_creature.get('id', '')}:lore:{parent_creature.get('generation', 0)}")
        return update_lore_local(parent_creature, evolution_decision, rng)

    def design_counter(
        self,
        dominant_creature: dict[str, Any],
        fight_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from backend.graphs.nodes.counter_logic import design_counter_local
        return design_counter_local(dominant_creature, fight_history)

    def generate_rival(
        self,
        dominant_creature: dict[str, Any],
        counter_design: dict[str, Any],
    ) -> dict[str, Any]:
        from backend.graphs.nodes.counter_logic import generate_rival_local
        return generate_rival_local(dominant_creature, counter_design)

    def generate_rival_taunts(
        self,
        dominant_creature: dict[str, Any],
        rival_concept: dict[str, Any],
    ) -> dict[str, list[str]]:
        from backend.graphs.nodes.concept_generator import generate_rival_taunts_local
        rng = Random(f"{dominant_creature.get('id', '')}:rival_taunts")
        return generate_rival_taunts_local(dominant_creature, rival_concept, rng)


    def gather_context(
        self,
        trigger_event: str,
        simulation_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "trigger_event": trigger_event,
            "top_creatures": simulation_snapshot.get("top_creatures", []),
            "recent_fights": simulation_snapshot.get("recent_fights", []),
            "element_counts": simulation_snapshot.get("element_counts", {}),
            "total_fights": simulation_snapshot.get("total_fights", 0),
        }

    def identify_narrative_threads(
        self,
        context: dict[str, Any],
    ) -> list[str]:
        from backend.graphs.nodes.concept_generator import identify_narrative_threads_local
        return identify_narrative_threads_local(context)

    def generate_commentary(
        self,
        trigger_event: str,
        narrative_threads: list[str],
        simulation_snapshot: dict[str, Any],
    ) -> list[str]:
        from backend.graphs.nodes.concept_generator import generate_commentary_local
        rng = Random(
            f"{trigger_event}:{len(narrative_threads)}:"
            f"{simulation_snapshot.get('total_fights', 0)}"
        )
        return generate_commentary_local(trigger_event, narrative_threads, simulation_snapshot, rng)


def get_gemini_provider() -> GeminiProvider:
    global _PROVIDER_SINGLETON

    settings = get_settings()
    if settings.app_env == "test" or not settings.google_api_key:
        return MockGeminiProvider()
    if _PROVIDER_SINGLETON is None:
        _PROVIDER_SINGLETON = RealGeminiProvider(
            settings.google_api_key,
            settings.gemini_model,
        )
    return _PROVIDER_SINGLETON


_PROVIDER_SINGLETON: GeminiProvider | None = None


# ---------------------------------------------------------------------------
# LangGraph node factories — each returns a pure (state) -> dict node function
# ---------------------------------------------------------------------------


def make_concept_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_generate_concept(state: dict[str, Any]) -> dict[str, Any]:
        concept = provider.generate_concept(state["seed_params"])
        logger.bind(stage="concept_generated", name=concept.get("name")).info(
            "creature_factory | concept generated"
        )
        return {
            "concept": concept,
            "visual_descriptor": concept.get("visual_descriptor"),
        }

    return node_generate_concept


def make_stats_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_generate_stats(state: dict[str, Any]) -> dict[str, Any]:
        generated = provider.generate_stats(state["seed_params"], state["concept"])
        selected_abilities = state["seed_params"].get("selected_abilities") or []
        abilities = selected_abilities if selected_abilities else generated.abilities
        logger.bind(stage="stats_generated").info("creature_factory | stats generated")
        return {"stats": generated.stats, "abilities": abilities}

    return node_generate_stats


def make_taunts_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_generate_taunts(state: dict[str, Any]) -> dict[str, Any]:
        taunts = provider.generate_taunts(state["seed_params"], state["concept"])
        logger.bind(stage="taunts_generated").info("creature_factory | taunts generated")
        return {"taunts": taunts}

    return node_generate_taunts


# ---------------------------------------------------------------------------
# Graph 2 — evolution node factories
# ---------------------------------------------------------------------------


def node_analyse_history(state: dict[str, Any]) -> dict[str, Any]:
    """DuckDB stub: derive fight patterns from state's fight_history list."""
    fight_history: list[dict[str, Any]] = state.get("fight_history") or []

    if not fight_history:
        return {
            "evolution_analysis": {
                "win_rate": 0.0,
                "weaknesses": [],
                "unused_abilities": [],
                "avg_turns": 0.0,
            }
        }

    wins = sum(1 for f in fight_history if f.get("won"))
    total = len(fight_history)
    weaknesses = list(
        {
            f["opponent_element"]
            for f in fight_history
            if not f.get("won") and "opponent_element" in f
        }
    )
    all_used: set[str] = set()
    for f in fight_history:
        all_used.update(f.get("abilities_used", []))
    turns = [f["turns"] for f in fight_history if "turns" in f]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    logger.bind(stage="analyse_history", wins=wins, total=total).info(
        "evolution | history analysed"
    )
    return {
        "evolution_analysis": {
            "win_rate": wins / total,
            "weaknesses": weaknesses,
            "unused_abilities": [],
            "avg_turns": avg_turns,
        }
    }


def make_decide_evolution_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_decide_evolution(state: dict[str, Any]) -> dict[str, Any]:
        analysis = state.get("evolution_analysis") or {}
        decision = provider.decide_evolution(state["parent_creature"], analysis)
        logger.bind(stage="decide_evolution", boosts=decision.get("stat_boosts")).info(
            "evolution | decision made"
        )
        return {"evolution_decision": decision}

    return node_decide_evolution


def make_generate_evolution_ability_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_generate_evolution_ability(state: dict[str, Any]) -> dict[str, Any]:
        ability = provider.generate_evolution_ability(
            state["parent_creature"], state["evolution_decision"]
        )
        logger.bind(stage="generate_evolution_ability", name=ability.get("name")).info(
            "evolution | new ability generated"
        )
        return {"evolution_new_ability": ability}

    return node_generate_evolution_ability


def make_update_lore_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_update_lore(state: dict[str, Any]) -> dict[str, Any]:
        new_lore = provider.update_lore(state["parent_creature"], state["evolution_decision"])
        logger.bind(stage="update_lore").info("evolution | lore updated")
        return {"evolution_updated_lore": new_lore}

    return node_update_lore


# ---------------------------------------------------------------------------
# Graph 3 — rival node factories
# ---------------------------------------------------------------------------


def make_profile_dominant_node(
    session: Any,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Loads the dominant creature + fight history from SQLite into state."""
    from sqlmodel import Session, select

    from backend.db.models import Ability, Fight

    def node_profile_dominant(state: dict[str, Any]) -> dict[str, Any]:
        dominant = state["dominant_creature"]
        creature_id = dominant["id"]

        # Load abilities from DB to enrich the profile
        with Session(session.get_bind()) as s:
            abilities = s.exec(
                select(Ability).where(Ability.creature_id == creature_id)
            ).all()
            fights = s.exec(
                select(Fight).where(
                    (Fight.creature_a_id == creature_id) | (Fight.creature_b_id == creature_id)
                )
            ).all()

        dominant["abilities"] = [
            {"name": a.name, "type": a.type, "effect": a.effect} for a in abilities
        ]
        fight_history = [
            {
                "fight_id": f.id,
                "won": f.winner_id == creature_id,
                "turns": f.duration_turns,
                "opponent_element": None,
            }
            for f in fights
        ]
        logger.bind(
            stage="profile_dominant",
            creature_id=creature_id,
            fights=len(fights),
        ).info("rival | dominant profiled")
        return {"dominant_creature": dominant, "fight_history": fight_history}

    return node_profile_dominant


def make_design_counter_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_design_counter(state: dict[str, Any]) -> dict[str, Any]:
        design = provider.design_counter(
            state["dominant_creature"], state.get("fight_history") or []
        )
        logger.bind(
            stage="design_counter",
            counter_element=design.get("counter_element"),
        ).info("rival | counter designed")
        return {"counter_design": design}

    return node_design_counter


def make_generate_rival_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_generate_rival(state: dict[str, Any]) -> dict[str, Any]:
        rival_concept = provider.generate_rival(
            state["dominant_creature"], state["counter_design"]
        )
        logger.bind(stage="generate_rival", name=rival_concept.get("name")).info(
            "rival | rival concept generated"
        )
        return {"concept": rival_concept}

    return node_generate_rival


def make_generate_rival_taunts_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_generate_rival_taunts(state: dict[str, Any]) -> dict[str, Any]:
        taunts = provider.generate_rival_taunts(state["dominant_creature"], state["concept"])
        logger.bind(stage="generate_rival_taunts").info("rival | taunts generated")
        return {"taunts": taunts}

    return node_generate_rival_taunts


# ---------------------------------------------------------------------------
# Graph 4 — commentary LangGraph node factories
# ---------------------------------------------------------------------------


def make_gather_context_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_gather_context(state: dict[str, Any]) -> dict[str, Any]:
        trigger = state.get("trigger_event") or "periodic"
        snapshot = state.get("simulation_snapshot") or {}
        context = provider.gather_context(trigger, snapshot)
        logger.bind(stage="gather_context", trigger=trigger).info(
            "commentary | context gathered"
        )
        return {"simulation_snapshot": {**snapshot, **context}}

    return node_gather_context


def make_identify_narrative_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_identify_narrative(state: dict[str, Any]) -> dict[str, Any]:
        context = state.get("simulation_snapshot") or {}
        threads = provider.identify_narrative_threads(context)
        logger.bind(stage="identify_narrative", threads=len(threads)).info(
            "commentary | narrative threads identified"
        )
        return {"narrative_threads": threads}

    return node_identify_narrative


def make_generate_commentary_node(
    provider: GeminiProvider,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_generate_commentary(state: dict[str, Any]) -> dict[str, Any]:
        trigger = state.get("trigger_event") or "periodic"
        threads = state.get("narrative_threads") or []
        snapshot = state.get("simulation_snapshot") or {}
        lines = provider.generate_commentary(trigger, threads, snapshot)
        logger.bind(stage="generate_commentary", lines=len(lines)).info(
            "commentary | lines generated"
        )
        return {"commentary_lines": lines}

    return node_generate_commentary
