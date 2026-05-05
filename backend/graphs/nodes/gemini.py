from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Protocol


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


def get_gemini_provider() -> GeminiProvider:
    """Returns the current provider adapter. Real API adapter will replace this later."""
    return MockGeminiProvider()
