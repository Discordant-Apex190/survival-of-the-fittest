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
        prompt = (
            "Generate a combat creature concept. Return ONLY JSON with keys: "
            "name,lore,personality,fighting_style,visual_descriptor,behavior_weights. "
            "behavior_weights must include attack, defend, ability as floats that sum near 1. "
            f"Seed params: {orjson.dumps(seed_params).decode()}"
        )
        try:
            out = self._call_json("generate_concept", prompt)
            return {
                "name": str(out["name"]),
                "lore": str(out["lore"]),
                "personality": str(out["personality"]),
                "fighting_style": str(out["fighting_style"]),
                "visual_descriptor": dict(out["visual_descriptor"]),
                "behavior_weights": dict(out["behavior_weights"]),
            }
        except Exception:  # noqa: BLE001
            return self._fallback.generate_concept(seed_params)

    def generate_stats(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> GeneratedStats:
        prompt = (
            "Generate balanced combat stats and abilities. Return ONLY JSON with keys stats and "
            "abilities. stats keys: health,attack,defense,speed (integers). "
            "abilities is a list of objects with "
            "name,type,energy_cost,cooldown,effect,description. "
            "Obey provided tier budget. "
            f"Seed params: {orjson.dumps(seed_params).decode()} "
            f"Concept: {orjson.dumps(concept).decode()}"
        )
        try:
            out = self._call_json("generate_stats", prompt)
            return GeneratedStats(stats=dict(out["stats"]), abilities=list(out["abilities"]))
        except Exception:  # noqa: BLE001
            return self._fallback.generate_stats(seed_params, concept)

    def generate_taunts(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> dict[str, list[str]]:
        prompt = (
            "Generate short taunts. Return ONLY JSON object with triggers "
            "intro,ability,win,loss,ko. "
            "Each value must be a list of 1-2 short lines. "
            f"Seed params: {orjson.dumps(seed_params).decode()} "
            f"Concept: {orjson.dumps(concept).decode()}"
        )
        try:
            out = self._call_json("generate_taunts", prompt)
            return {k: list(v) for k, v in dict(out).items()}
        except Exception:  # noqa: BLE001
            return self._fallback.generate_taunts(seed_params, concept)

    def decide_evolution(
        self, parent_creature: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]:
        prompt = (
            "Decide evolution changes. Return ONLY JSON with stat_boosts (object), "
            "new_ability_slot (boolean), reasoning (string). "
            f"Parent: {orjson.dumps(parent_creature).decode()} "
            f"Analysis: {orjson.dumps(analysis).decode()}"
        )
        try:
            out = self._call_json("decide_evolution", prompt)
            return {
                "stat_boosts": dict(out.get("stat_boosts", {})),
                "new_ability_slot": bool(out.get("new_ability_slot", False)),
                "reasoning": str(out.get("reasoning", "")),
            }
        except Exception:  # noqa: BLE001
            return self._fallback.decide_evolution(parent_creature, analysis)

    def generate_evolution_ability(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> dict[str, Any]:
        prompt = (
            "Generate one evolved ability. Return ONLY JSON with keys "
            "name,type,energy_cost,cooldown,effect,description. "
            f"Parent: {orjson.dumps(parent_creature).decode()} "
            f"Decision: {orjson.dumps(evolution_decision).decode()}"
        )
        try:
            out = self._call_json("generate_evolution_ability", prompt)
            return {
                "name": str(out["name"]),
                "type": str(out["type"]),
                "energy_cost": int(out["energy_cost"]),
                "cooldown": int(out["cooldown"]),
                "effect": str(out["effect"]),
                "description": str(out["description"]),
            }
        except Exception:  # noqa: BLE001
            return self._fallback.generate_evolution_ability(parent_creature, evolution_decision)

    def update_lore(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> str:
        prompt = (
            "Rewrite this lore in 1-2 sentences after evolution. Return plain text only. "
            f"Parent: {orjson.dumps(parent_creature).decode()} "
            f"Decision: {orjson.dumps(evolution_decision).decode()}"
        )
        try:
            text = self._call_model(prompt, json_mode=False)
            return text.strip()
        except Exception:  # noqa: BLE001
            return self._fallback.update_lore(parent_creature, evolution_decision)

    def design_counter(
        self,
        dominant_creature: dict[str, Any],
        fight_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = (
            "Design a strategic counter for a dominant arena creature. Return ONLY JSON with keys "
            "counter_element,counter_archetype,target_weak_stat,target_strong_stat,"
            "strategy,boost_stat. "
            f"Dominant: {orjson.dumps(dominant_creature).decode()} "
            f"Fight history: {orjson.dumps(fight_history).decode()}"
        )
        try:
            out = self._call_json("design_counter", prompt)
            return dict(out)
        except Exception:  # noqa: BLE001
            return self._fallback.design_counter(dominant_creature, fight_history)

    def generate_rival(
        self,
        dominant_creature: dict[str, Any],
        counter_design: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = (
            "Generate a rival creature concept meant to dethrone the dominant creature. "
            "Return ONLY JSON with keys "
            "name,lore,personality,fighting_style,visual_descriptor,behavior_weights,"
            "counter_element,counter_archetype. "
            f"Dominant: {orjson.dumps(dominant_creature).decode()} "
            f"Counter design: {orjson.dumps(counter_design).decode()}"
        )
        try:
            out = self._call_json("generate_rival", prompt)
            return dict(out)
        except Exception:  # noqa: BLE001
            return self._fallback.generate_rival(dominant_creature, counter_design)

    def generate_rival_taunts(
        self,
        dominant_creature: dict[str, Any],
        rival_concept: dict[str, Any],
    ) -> dict[str, list[str]]:
        prompt = (
            "Generate rival taunts. Return ONLY JSON with triggers "
            "intro,ability,win,loss,ko; values "
            "must be lists of 1-2 lines. "
            f"Dominant: {orjson.dumps(dominant_creature).decode()} "
            f"Rival: {orjson.dumps(rival_concept).decode()}"
        )
        try:
            out = self._call_json("generate_rival_taunts", prompt)
            return {k: list(v) for k, v in dict(out).items()}
        except Exception:  # noqa: BLE001
            return self._fallback.generate_rival_taunts(dominant_creature, rival_concept)

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
        prompt = (
            "Identify 2 concise narrative threads for arena commentary. Return ONLY JSON array of "
            "strings. "
            f"Context: {orjson.dumps(context).decode()}"
        )
        try:
            out = self._call_json("identify_narrative_threads", prompt)
            if isinstance(out, list):
                return [str(v) for v in out]
            return self._fallback.identify_narrative_threads(context)
        except Exception:  # noqa: BLE001
            return self._fallback.identify_narrative_threads(context)

    def generate_commentary(
        self,
        trigger_event: str,
        narrative_threads: list[str],
        simulation_snapshot: dict[str, Any],
    ) -> list[str]:
        prompt = (
            "Generate 2 vivid lines of arena commentary as The Chronicler. "
            "Return ONLY JSON array of "
            "strings (2 items, 10-200 chars each). "
            f"Trigger: {trigger_event}. Threads: {orjson.dumps(narrative_threads).decode()} "
            f"Snapshot: {orjson.dumps(simulation_snapshot).decode()}"
        )
        try:
            out = self._call_json("generate_commentary", prompt)
            if isinstance(out, list):
                return [str(v) for v in out]
            return self._fallback.generate_commentary(
                trigger_event, narrative_threads, simulation_snapshot
            )
        except Exception:  # noqa: BLE001
            return self._fallback.generate_commentary(
                trigger_event, narrative_threads, simulation_snapshot
            )


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
        rng = self._rng(seed_params)
        element = seed_params["element"].title()
        archetype = seed_params["archetype"].title()
        biome = seed_params["biome"].title()
        suffix = rng.choice(["Warden", "Howl", "Spire", "Shade", "Fang"])
        name = f"{element} {archetype} {suffix}"
        return {
            "name": name,
            "lore": f"Forged in the {biome}, {name} thrives in unforgiving arenas.",
            "personality": rng.choice(["aggressive", "calculating", "disciplined", "chaotic"]),
            "fighting_style": rng.choice(["rushdown", "counter", "zoning", "brawler"]),
            "visual_descriptor": {
                "silhouette": rng.choice(["lean", "towering", "hulking"]),
                "palette": [
                    seed_params["element"],
                    rng.choice(["obsidian", "gold", "ash", "teal"]),
                ],
            },
            "behavior_weights": {
                "attack": round(rng.uniform(0.3, 0.7), 2),
                "defend": round(rng.uniform(0.1, 0.4), 2),
                "ability": round(rng.uniform(0.1, 0.4), 2),
            },
        }

    def generate_stats(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> GeneratedStats:
        rng = self._rng(seed_params)
        budget = int(seed_params["stat_budget"])

        max_single_stat = {"common": 25, "uncommon": 30, "rare": 38, "legendary": 50}[
            seed_params["tier"]
        ]
        stat_names = ["health", "attack", "defense", "speed"]

        # Allocate budget while respecting max-single-stat constraints for each tier.
        remaining = budget
        stats: dict[str, int] = {}
        for index, stat_name in enumerate(stat_names):
            remaining_slots = len(stat_names) - index - 1
            min_for_slot = max(1, remaining - (remaining_slots * max_single_stat))
            max_for_slot = min(max_single_stat, remaining - remaining_slots)
            value = rng.randint(min_for_slot, max_for_slot)
            stats[stat_name] = value
            remaining -= value

        max_slots = {"common": 1, "uncommon": 2, "rare": 3, "legendary": 4}[seed_params["tier"]]
        ability_count = max(1, min(max_slots, 2))

        abilities: list[dict[str, Any]] = []
        for idx in range(ability_count):
            ability_name = rng.choice(
                ["Rift Slash", "Ember Arc", "Stone Pulse", "Volt Pin", "Frost Lock"]
            )
            abilities.append(
                {
                    "name": f"{ability_name} {idx + 1}",
                    "type": seed_params["element"],
                    "energy_cost": 8 + (idx * 4),
                    "cooldown": 1 + idx,
                    "effect": rng.choice(["damage", "stun", "slow", "shield_break"]),
                    "description": (
                        f"{concept['name']} uses {ability_name.lower()} "
                        "to pressure opponents."
                    ),
                }
            )

        return GeneratedStats(stats=stats, abilities=abilities)

    def generate_taunts(
        self, seed_params: dict[str, Any], concept: dict[str, Any]
    ) -> dict[str, list[str]]:
        _ = seed_params
        name = concept["name"]
        return {
            "intro": [f"I am {name}. The arena remembers me."],
            "ability": ["You felt that before you saw it."],
            "win": ["Another lesson carved into the sand."],
            "loss": ["I learn. I return sharper."],
            "ko": ["Kneel. Adapt or vanish."],
        }

    def decide_evolution(
        self, parent_creature: dict[str, Any], analysis: dict[str, Any]
    ) -> dict[str, Any]:
        rng = Random(f"{parent_creature['id']}:evolution:{parent_creature['generation']}")
        tier = parent_creature["tier"]
        max_single = _TIER_MAX_SINGLE[tier]
        current_stats: dict[str, int] = parent_creature["stats"]
        stat_names = ["health", "attack", "defense", "speed"]
        n_boosts = rng.randint(1, 2)
        chosen = rng.sample(stat_names, n_boosts)
        stat_boosts: dict[str, int] = {}
        for s in chosen:
            headroom = max_single - current_stats.get(s, 0)
            if headroom <= 0:
                continue
            boost = min(rng.randint(2, 5), headroom)
            if boost > 0:
                stat_boosts[s] = boost
        weaknesses = [w for w in analysis.get("weaknesses", []) if w is not None]
        new_ability_slot = bool(weaknesses) and rng.random() < 0.5
        reasoning = (
            f"Adapted to address {', '.join(weaknesses)} weaknesses."
            if weaknesses
            else "Refined core strengths through repeated combat."
        )
        return {
            "stat_boosts": stat_boosts,
            "new_ability_slot": new_ability_slot,
            "reasoning": reasoning,
        }

    def generate_evolution_ability(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> dict[str, Any]:
        _ = evolution_decision
        rng = Random(f"{parent_creature['id']}:new_ability:{parent_creature['generation']}")
        ability_name = rng.choice(
            ["Rift Slash", "Ember Arc", "Stone Pulse", "Volt Pin", "Frost Lock"]
        )
        return {
            "name": f"Evolved {ability_name}",
            "type": parent_creature["element"],
            "energy_cost": rng.randint(10, 20),
            "cooldown": rng.randint(2, 4),
            "effect": rng.choice(["damage", "stun", "slow", "shield_break"]),
            "description": (
                f"A power awakened in {parent_creature['name']} through conflict."
            ),
        }

    def update_lore(
        self, parent_creature: dict[str, Any], evolution_decision: dict[str, Any]
    ) -> str:
        original = parent_creature.get("lore", "")
        reasoning = evolution_decision.get("reasoning", "battle-hardened by conflict")
        return f"{original} Through trial, {parent_creature['name']} evolved: {reasoning}"

    def design_counter(
        self,
        dominant_creature: dict[str, Any],
        fight_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        stats = dominant_creature.get("stats", {})
        # Identify the dominant creature's weakest stats to counter with opposite strengths
        sorted_stats = sorted(stats.items(), key=lambda kv: kv[1])
        dominant_weak_stat = sorted_stats[0][0] if sorted_stats else "defense"
        dominant_strong_stat = sorted_stats[-1][0] if sorted_stats else "attack"

        element_counters = {
            "fire": "ice",
            "ice": "electric",
            "electric": "nature",
            "nature": "void",
            "void": "fire",
        }
        target_element = dominant_creature.get("element", "fire")
        counter_element = element_counters.get(target_element, target_element)

        counter_archetype = {
            "berserker": "sentinel",
            "sentinel": "trickster",
            "trickster": "stalker",
            "stalker": "guardian",
            "guardian": "berserker",
        }.get(dominant_creature.get("fighting_style", "brawler"), "trickster")

        strategy = (
            f"Counter {dominant_creature['name']}'s {dominant_strong_stat} dominance "
            f"by exploiting their {dominant_weak_stat}. "
            f"Use {counter_element} element to neutralise their {target_element} strengths."
        )
        return {
            "counter_element": counter_element,
            "counter_archetype": counter_archetype,
            "target_weak_stat": dominant_weak_stat,
            "target_strong_stat": dominant_strong_stat,
            "strategy": strategy,
            "boost_stat": dominant_weak_stat,  # rival will be strong where dominant is weak
        }

    def generate_rival(
        self,
        dominant_creature: dict[str, Any],
        counter_design: dict[str, Any],
    ) -> dict[str, Any]:
        rng = Random(f"{dominant_creature['id']}:rival:generate")
        dominant_name = dominant_creature.get("name", "Unknown")
        counter_element = counter_design["counter_element"]
        counter_archetype = counter_design["counter_archetype"]
        suffix = rng.choice(["Nemesis", "Bane", "Scourge", "Ruin", "Vex"])
        rival_name = f"{counter_element.title()} {suffix} of {dominant_name}"

        return {
            "name": rival_name,
            "lore": (
                f"Born from the shadow of {dominant_name}'s reign. "
                f"Every scar carved by that creature became a lesson. "
                f"{rival_name} exists for one purpose: to end the streak."
            ),
            "personality": rng.choice(["obsessed", "cold", "relentless", "calculating"]),
            "fighting_style": counter_archetype,
            "visual_descriptor": {
                "silhouette": rng.choice(["angular", "predatory", "mirrored"]),
                "palette": [counter_element, "obsidian"],
            },
            "behavior_weights": {
                "aggression": round(0.4 + rng.uniform(0.0, 0.3), 2),
                "caution": round(0.2 + rng.uniform(0.0, 0.2), 2),
                "cunning": round(0.4 + rng.uniform(0.0, 0.3), 2),
                "risk_tolerance": round(0.5 + rng.uniform(0.0, 0.2), 2),
            },
            "counter_element": counter_element,
            "counter_archetype": counter_archetype,
        }

    def generate_rival_taunts(
        self,
        dominant_creature: dict[str, Any],
        rival_concept: dict[str, Any],
    ) -> dict[str, list[str]]:
        dominant_name = dominant_creature.get("name", "Unknown")
        return {
            "intro": [
                f"I've watched every one of your fights, {dominant_name}.",
                "Every win you celebrate brought me one step closer.",
            ],
            "ability": [
                f"You won't see this one coming, {dominant_name}.",
            ],
            "win": [
                f"The streak ends here. The arena forgets you, {dominant_name}.",
            ],
            "loss": [
                f"This isn't over, {dominant_name}. I was made for this.",
            ],
            "ko": [
                f"Fall. The era of {dominant_name} is over.",
            ],
        }


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
        threads: list[str] = []
        trigger = context.get("trigger_event", "periodic")
        top = context.get("top_creatures", [])

        if trigger == "extinction":
            threads.append("A bloodline ends — the arena claims another victim.")
        elif trigger == "rival_spawned":
            threads.append("A rival emerges from the shadow of a dominant reign.")
        elif trigger == "evolution":
            threads.append("Evolution stirs — a creature transforms beyond its origin.")
        elif trigger == "win_streak":
            threads.append("The streak continues — dominance carved fight by fight.")
        else:
            threads.append("The arena churns. Blood and glory. Nothing more.")

        if top:
            champion = top[0].get("name", "the champion")
            threads.append(f"{champion} stands above the rest — for now.")

        return threads

    def generate_commentary(
        self,
        trigger_event: str,
        narrative_threads: list[str],
        simulation_snapshot: dict[str, Any],
    ) -> list[str]:
        rng = Random(f"{trigger_event}:{len(narrative_threads)}")
        lines = [narrative_threads[0]] if narrative_threads else ["The arena watches."]
        extras = [
            "The strong survive. The weak become legend.",
            "Every fight rewrites the hierarchy.",
            "Power is borrowed. It is always reclaimed.",
        ]
        lines.append(rng.choice(extras))
        return lines


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
        logger.bind(stage="stats_generated").info("creature_factory | stats generated")
        return {"stats": generated.stats, "abilities": generated.abilities}

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
