"""Pure-logic counter design and rival concept generation — no LLM required."""
from __future__ import annotations

import random
from typing import Any

# ---------------------------------------------------------------------------
# Counter tables
# ---------------------------------------------------------------------------

ELEMENT_WHEEL: dict[str, str] = {
    "fire":     "ice",
    "ice":      "electric",
    "electric": "nature",
    "nature":   "void",
    "void":     "fire",
}

ARCHETYPE_COUNTER: dict[str, str] = {
    "berserker": "sentinel",
    "sentinel":  "trickster",
    "trickster": "stalker",
    "stalker":   "guardian",
    "guardian":  "berserker",
    # Fallbacks for non-standard fighting_style values
    "rushdown":  "sentinel",
    "brawler":   "trickster",
    "counter":   "stalker",
    "zoning":    "guardian",
}

_STRATEGY_TEMPLATES: dict[str, list[str]] = {
    ("berserker", "sentinel"): [
        "Wall off their aggression. {name}'s reckless attacks will shatter against superior defense.",
        "Let {name} exhaust themselves. A sentinel outlasts a berserker every time.",
    ],
    ("sentinel", "trickster"): [
        "A sentinel can't guard what it can't predict. Feints and repositioning will unravel {name}.",
        "{name} is too slow to counter cunning. Trick them, then punish.",
    ],
    ("trickster", "stalker"): [
        "A stalker reads feints through patience. {name}'s tricks won't work under sustained pressure.",
        "Hunt {name} methodically. Their speed means nothing if cornered.",
    ],
    ("stalker", "guardian"): [
        "{name} hunts alone — a guardian's bulk and endurance negates the stalker's edge.",
        "Outlast {name}. Guardians wear down stalkers through attrition.",
    ],
    ("guardian", "berserker"): [
        "Pure offense shatters a guardian's complacency. Overwhelm {name} before they can recover.",
        "{name} relies on outlasting opponents. A berserker denies them that luxury.",
    ],
}

_DEFAULT_STRATEGY = "Counter {name}'s {strong} with superior {weak} targeting."

# ---------------------------------------------------------------------------
# Rival name generation
# ---------------------------------------------------------------------------

_RIVAL_PREFIXES: dict[str, list[str]] = {
    "fire":     ["Pyrax", "Scorch", "Embrix", "Charven", "Ignath"],
    "ice":      ["Glacex", "Crioval", "Rimeth", "Keldar", "Frostyn"],
    "electric": ["Voltix", "Arcath", "Zaphor", "Galdren", "Thundex"],
    "void":     ["Nyxar", "Vethis", "Abyssin", "Nullen", "Riftax"],
    "nature":   ["Sylvar", "Thornex", "Grovath", "Sporax", "Ferneth"],
}

_RIVAL_SUFFIXES: list[str] = [
    "bane", "nemesis", "scourge", "ruin", "vex", "end", "fall", "doom",
]

_RIVAL_LORE_TEMPLATES: list[str] = [
    (
        "Born from the shadow of {dominant_name}'s reign. "
        "Every victory that creature claimed sharpened a single edge — "
        "the one that will end it. {rival_name} exists for one purpose."
    ),
    (
        "They watched {dominant_name} win, and win again. "
        "Each fight was a lesson. Now the lesson is complete. "
        "The arena will know {rival_name}."
    ),
    (
        "{dominant_name} carved a streak through this arena. "
        "{rival_name} emerged from those ruins, harder. "
        "The reckoning comes."
    ),
]

_RIVAL_PERSONALITIES: list[str] = ["obsessed", "cold", "relentless", "calculating", "vengeful"]

# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def design_counter_local(
    dominant_creature: dict[str, Any],
    fight_history: list[dict[str, Any]],  # noqa: ARG001
) -> dict[str, Any]:
    """Compute a counter design for the dominant creature using pure logic."""
    stats = dominant_creature.get("stats", {})
    sorted_stats = sorted(stats.items(), key=lambda kv: kv[1])
    dominant_weak_stat   = sorted_stats[0][0]  if sorted_stats else "defense"
    dominant_strong_stat = sorted_stats[-1][0] if sorted_stats else "attack"

    target_element   = dominant_creature.get("element", "fire")
    counter_element  = ELEMENT_WHEEL.get(target_element, "ice")
    dominant_style   = dominant_creature.get("fighting_style", "brawler")
    counter_archetype = ARCHETYPE_COUNTER.get(dominant_style, "trickster")

    pair = (dominant_style, counter_archetype)
    templates = _STRATEGY_TEMPLATES.get(pair, [_DEFAULT_STRATEGY])
    strategy = templates[0].format(
        name=dominant_creature.get("name", "the dominant"),
        strong=dominant_strong_stat,
        weak=dominant_weak_stat,
    )

    return {
        "counter_element":    counter_element,
        "counter_archetype":  counter_archetype,
        "target_weak_stat":   dominant_weak_stat,
        "target_strong_stat": dominant_strong_stat,
        "strategy":           strategy,
        "boost_stat":         dominant_weak_stat,
    }


def generate_rival_local(
    dominant_creature: dict[str, Any],
    counter_design: dict[str, Any],
) -> dict[str, Any]:
    """Build a rival creature concept from counter design — no LLM needed."""
    dominant_name    = dominant_creature.get("name", "Unknown")
    counter_element  = counter_design["counter_element"]
    counter_archetype = counter_design["counter_archetype"]

    rng = random.Random(f"{dominant_creature.get('id', dominant_name)}:rival:concept")

    prefix  = rng.choice(_RIVAL_PREFIXES.get(counter_element, _RIVAL_PREFIXES["void"]))
    suffix  = rng.choice(_RIVAL_SUFFIXES)
    rival_name = f"{prefix} {suffix.title()}"

    lore_template = rng.choice(_RIVAL_LORE_TEMPLATES)
    lore = lore_template.format(dominant_name=dominant_name, rival_name=rival_name)

    behavior_weights = {
        "aggression":     round(0.40 + rng.uniform(0.0, 0.30), 2),
        "caution":        round(0.20 + rng.uniform(0.0, 0.20), 2),
        "cunning":        round(0.40 + rng.uniform(0.0, 0.30), 2),
        "risk_tolerance": round(0.50 + rng.uniform(0.0, 0.20), 2),
    }

    return {
        "name":             rival_name,
        "lore":             lore,
        "personality":      rng.choice(_RIVAL_PERSONALITIES),
        "fighting_style":   counter_archetype,
        "visual_descriptor": {
            "silhouette": rng.choice(["angular", "predatory", "mirrored"]),
            "palette":    [counter_element, "obsidian"],
        },
        "behavior_weights":  behavior_weights,
        "counter_element":   counter_element,
        "counter_archetype": counter_archetype,
    }
