"""Local stat and ability generation — no LLM required."""
from __future__ import annotations

import random
from typing import Any

# ---------------------------------------------------------------------------
# Archetype bias table
# ---------------------------------------------------------------------------

ARCHETYPE_BIAS: dict[str, dict[str, float]] = {
    "berserker": {"health": 0.30, "attack": 0.40, "defense": 0.10, "speed": 0.20},
    "sentinel":  {"health": 0.35, "attack": 0.15, "defense": 0.40, "speed": 0.10},
    "trickster": {"health": 0.15, "attack": 0.30, "defense": 0.15, "speed": 0.40},
    "stalker":   {"health": 0.20, "attack": 0.35, "defense": 0.10, "speed": 0.35},
    "guardian":  {"health": 0.40, "attack": 0.15, "defense": 0.35, "speed": 0.10},
}

_DEFAULT_BIAS: dict[str, float] = {"health": 0.25, "attack": 0.30, "defense": 0.25, "speed": 0.20}

_STAT_NAMES = ["health", "attack", "defense", "speed"]

# ---------------------------------------------------------------------------
# Ability matrix
# ---------------------------------------------------------------------------

ABILITY_MATRIX: dict[str, list[dict[str, Any]]] = {
    "fire": [
        {"name": "Ember Arc",        "type": "fire", "energy_cost": 12, "cooldown": 2, "effect": "damage",       "description": "A blazing arc of flame sears the target."},
        {"name": "Inferno Pulse",    "type": "fire", "energy_cost": 18, "cooldown": 3, "effect": "stun",         "description": "A pulse of superheated air stuns briefly."},
        {"name": "Cinder Rush",      "type": "fire", "energy_cost": 10, "cooldown": 1, "effect": "damage",       "description": "A raking dash trailing burning embers."},
        {"name": "Molten Shatter",   "type": "fire", "energy_cost": 20, "cooldown": 4, "effect": "shield_break", "description": "Molten force shatters all defensive stances."},
    ],
    "ice": [
        {"name": "Frost Lock",       "type": "ice", "energy_cost": 14, "cooldown": 2, "effect": "slow",         "description": "Glacial chains sap the target's speed."},
        {"name": "Shard Volley",     "type": "ice", "energy_cost": 10, "cooldown": 1, "effect": "damage",       "description": "A spray of razor-edged ice crystals."},
        {"name": "Cryo Burst",       "type": "ice", "energy_cost": 20, "cooldown": 3, "effect": "stun",         "description": "A sudden freeze stuns the target solid."},
        {"name": "Glacial Shatter",  "type": "ice", "energy_cost": 16, "cooldown": 2, "effect": "shield_break", "description": "Expanding ice fractures through any guard."},
    ],
    "electric": [
        {"name": "Volt Pin",         "type": "electric", "energy_cost": 12, "cooldown": 2, "effect": "shield_break", "description": "Precision lightning pierces defensive postures."},
        {"name": "Arc Chain",        "type": "electric", "energy_cost": 16, "cooldown": 3, "effect": "damage",       "description": "Arcing electricity leaps from strike to strike."},
        {"name": "Static Burst",     "type": "electric", "energy_cost": 10, "cooldown": 1, "effect": "slow",         "description": "Electrostatic discharge momentarily slows."},
        {"name": "Thunder Crash",    "type": "electric", "energy_cost": 22, "cooldown": 4, "effect": "stun",         "description": "A deafening thunderclap stuns on impact."},
    ],
    "void": [
        {"name": "Rift Slash",       "type": "void", "energy_cost": 14, "cooldown": 2, "effect": "damage",       "description": "A blade of collapsed space tears through defenses."},
        {"name": "Void Grasp",       "type": "void", "energy_cost": 18, "cooldown": 3, "effect": "slow",         "description": "Dimensional drag slows the target's movement."},
        {"name": "Null Strike",      "type": "void", "energy_cost": 10, "cooldown": 1, "effect": "shield_break", "description": "Anti-matter force negates all defensive stances."},
        {"name": "Event Horizon",    "type": "void", "energy_cost": 24, "cooldown": 4, "effect": "stun",         "description": "Brief temporal collapse stuns the target."},
    ],
    "nature": [
        {"name": "Root Bind",        "type": "nature", "energy_cost": 12, "cooldown": 2, "effect": "slow",         "description": "Rapid root growth entangles and slows the target."},
        {"name": "Thorn Volley",     "type": "nature", "energy_cost": 10, "cooldown": 1, "effect": "damage",       "description": "A barrage of sharpened thorns."},
        {"name": "Spore Burst",      "type": "nature", "energy_cost": 16, "cooldown": 3, "effect": "stun",         "description": "Disorienting spores stun briefly on inhale."},
        {"name": "Bark Shatter",     "type": "nature", "energy_cost": 18, "cooldown": 3, "effect": "shield_break", "description": "Hardened bark projectile shatters defensive guards."},
    ],
}

# ---------------------------------------------------------------------------
# Stat allocation
# ---------------------------------------------------------------------------

def _allocate_stats(bias: dict[str, float], budget: int, max_single: int) -> dict[str, int]:
    """Allocate stat budget according to bias weights.

    Guarantees: sum == budget, each stat in [1, max_single].
    """
    sorted_stats = sorted(_STAT_NAMES, key=lambda s: bias.get(s, 0.25), reverse=True)

    result = {s: max(1, min(int(bias.get(s, 0.25) * budget), max_single)) for s in _STAT_NAMES}

    remainder = budget - sum(result.values())

    if remainder > 0:
        for s in sorted_stats:
            if remainder <= 0:
                break
            headroom = max_single - result[s]
            add = min(remainder, headroom)
            result[s] += add
            remainder -= add
    elif remainder < 0:
        for s in reversed(sorted_stats):
            if remainder >= 0:
                break
            can_remove = result[s] - 1
            remove = min(-remainder, can_remove)
            result[s] -= remove
            remainder += remove

    return result


# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------

def generate_stats_local(
    archetype: str,
    element: str,
    tier: str,
    rng: random.Random,
) -> Any:
    """Return a GeneratedStats with deterministic archetype-biased allocation."""
    from backend.graphs.nodes.gemini import GeneratedStats
    from backend.graphs.nodes.validators import TIER_BUDGETS

    budget, max_single, max_slots = TIER_BUDGETS[tier]
    bias = ARCHETYPE_BIAS.get(archetype, _DEFAULT_BIAS)
    stats = _allocate_stats(bias, budget, max_single)

    element_pool = list(ABILITY_MATRIX.get(element, ABILITY_MATRIX["fire"]))
    rng.shuffle(element_pool)
    abilities = element_pool[:max_slots]

    return GeneratedStats(stats=stats, abilities=abilities)


def generate_evolution_ability_local(
    parent_creature: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    """Pick a new ability from the element matrix, avoiding duplicates."""
    element = parent_creature.get("element", "fire")
    existing_names = {a.get("name", "") for a in parent_creature.get("abilities", [])}

    pool = [
        a for a in ABILITY_MATRIX.get(element, ABILITY_MATRIX["fire"])
        if a["name"] not in existing_names
    ]

    if not pool:
        base = rng.choice(ABILITY_MATRIX.get(element, ABILITY_MATRIX["fire"]))
        return {
            **base,
            "name": f"Evolved {base['name']}",
            "energy_cost": min(30, base["energy_cost"] + 4),
            "cooldown": base["cooldown"] + 1,
            "description": (
                f"A mastered form of {base['name'].lower()}, "
                f"awakened in {parent_creature['name']} through conflict."
            ),
        }

    return dict(rng.choice(pool))
