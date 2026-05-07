"""Local concept, taunt, lore, and commentary generation — no LLM required.

Replaces the remaining Gemini calls:
  - generate_concept()          (creature creation)
  - generate_taunts()           (creature creation)
  - update_lore()               (evolution)
  - generate_rival_taunts()     (rival creation)
  - identify_narrative_threads() (commentary)
  - generate_commentary()       (commentary)
"""
from __future__ import annotations

import random
from typing import Any

# ---------------------------------------------------------------------------
# Name pools (phoneme-composed per element, 20 per element for variety)
# ---------------------------------------------------------------------------

_NAMES: dict[str, list[str]] = {
    "fire": [
        "Ignar",   "Pyrath",  "Embrix",  "Scorch",   "Blazen",
        "Cindar",  "Flamex",  "Infern",  "Ignos",    "Pyrex",
        "Ashrak",  "Embrax",  "Solarth", "Herak",    "Cinder",
        "Pyraxis", "Ignath",  "Blazvex", "Scorvax",  "Embrath",
    ],
    "ice": [
        "Glacen",  "Crysoph", "Frostax", "Rimeth",  "Keldax",
        "Shardis", "Frigus",  "Glacix",  "Crystar", "Frostis",
        "Rimvex",  "Keldeth", "Shardak", "Blizath", "Hailrix",
        "Glacorn", "Cryovex", "Frosten", "Shardex", "Rimaxor",
    ],
    "electric": [
        "Voltax",   "Arceth",  "Zaphyr",   "Galvrix", "Thundak",
        "Joltix",   "Sparkos", "Elaxis",   "Voltris", "Arcon",
        "Zaphrax",  "Galvern", "Thundis",  "Jolthor", "Sparken",
        "Voltorn",  "Arcvex",  "Thundvax", "Zaphos",  "Galvor",
    ],
    "void": [
        "Nyxath",  "Abyssar", "Nullex",  "Riftax",  "Vethis",
        "Shadon",  "Obsidar", "Voidex",  "Nyxorn",  "Abyssen",
        "Nullrix", "Riftvex", "Vethar",  "Shadrix",  "Obsidex",
        "Nyx",     "Vethax",  "Nullthar","Riftorn",  "Abyssix",
    ],
    "nature": [
        "Sylvar",  "Thornex", "Rootax",  "Sporax",  "Groveth",
        "Fernis",  "Leaforn", "Barkis",  "Sylvorn", "Thornak",
        "Rootis",  "Sporeth", "Grovax",  "Fernix",  "Leafris",
        "Sylvex",  "Thornath","Rootorn", "Sporrix", "Grovorn",
    ],
}

# ---------------------------------------------------------------------------
# Lore templates
# ---------------------------------------------------------------------------

_LORE_TEMPLATES: list[str] = [
    "Born in the heart of the {biome}, {name} knows only the brutality of the arena.",
    "The {biome} shaped {name} into a weapon — every scar a lesson, every victory a testament.",
    "From the depths of the {biome} emerged {name}, forged by {element} and relentless combat.",
    "Survivors of the {biome} are few. {name} is one. The arena will know why.",
    "{name} carries the essence of {element}. The {biome} taught it how to use it.",
    "In the {biome}, {name} learned that hesitation is death. The arena confirms it every fight.",
    "The {biome} gave {name} its power. The arena gives it purpose.",
    "Many enter the arena. Few carry {name}'s history from the {biome}.",
    "Hardened by the {biome}, {name} emerged as something the arena has never faced before.",
    "The {element} flows through {name} like blood — forged over countless seasons in the {biome}.",
]

# ---------------------------------------------------------------------------
# Personality per archetype
# ---------------------------------------------------------------------------

_PERSONALITIES: dict[str, list[str]] = {
    "berserker": ["aggressive", "relentless", "brutal", "savage", "unstoppable"],
    "sentinel":  ["disciplined", "patient", "unwavering", "methodical", "resolute"],
    "trickster": ["cunning", "elusive", "deceptive", "calculating", "unpredictable"],
    "stalker":   ["predatory", "focused", "cold", "persistent", "relentless"],
    "guardian":  ["protective", "stoic", "enduring", "steadfast", "unyielding"],
}
_DEFAULT_PERSONALITIES = ["fierce", "calculating", "tenacious", "driven", "ruthless"]

# ---------------------------------------------------------------------------
# Behavior weights per archetype — correct engine keys
# ---------------------------------------------------------------------------

_BEHAVIOR_WEIGHTS: dict[str, dict[str, float]] = {
    "berserker": {"aggression": 0.82, "caution": 0.10, "cunning": 0.22, "risk_tolerance": 0.80},
    "sentinel":  {"aggression": 0.22, "caution": 0.78, "cunning": 0.38, "risk_tolerance": 0.18},
    "trickster": {"aggression": 0.38, "caution": 0.42, "cunning": 0.88, "risk_tolerance": 0.55},
    "stalker":   {"aggression": 0.62, "caution": 0.28, "cunning": 0.72, "risk_tolerance": 0.65},
    "guardian":  {"aggression": 0.18, "caution": 0.88, "cunning": 0.28, "risk_tolerance": 0.12},
}
_DEFAULT_WEIGHTS: dict[str, float] = {
    "aggression": 0.50, "caution": 0.30, "cunning": 0.30, "risk_tolerance": 0.40,
}

# ---------------------------------------------------------------------------
# Taunt pool — element × archetype × trigger
# ---------------------------------------------------------------------------

_TAUNTS: dict[str, dict[str, dict[str, list[str]]]] = {
    "fire": {
        "berserker": {
            "intro":   ["{name} is here. Everything else is fuel.",
                        "Stand close. You will learn the meaning of heat."],
            "ability": ["You won't survive this one.",
                        "Feel what {element} can do."],
            "win":     ["Ash. That is all you are now.",
                        "Faster next time — if there is one."],
            "loss":    ["This fight is not over.",
                        "I learn. I return harder."],
            "ko":      ["Down. Stay there.",
                        "The {element} does not forgive weakness."],
        },
        "sentinel":  {
            "intro":   ["I am the wall you cannot break.",
                        "{name} stands. Nothing passes."],
            "ability": ["This ends here.",
                        "Burning walls do not fall."],
            "win":     ["Discipline outlasts fury every time.",
                        "You brought heat. I brought endurance."],
            "loss":    ["A wall bends but does not break.",
                        "Another fight. Another lesson in patience."],
            "ko":      ["The {element} holds. I do not.",
                        "Even walls fall. Eventually."],
        },
        "trickster": {
            "intro":   ["You can't hit what you can't see. Watch.",
                        "{name} does not fight fairly. Why would I?"],
            "ability": ["Did you see that coming? Didn't think so.",
                        "Misdirection. Then {element}."],
            "win":     ["The trick was not the move. It was the setup.",
                        "You were fighting the wrong fight the whole time."],
            "loss":    ["I reveal nothing. Not even my failures.",
                        "You got lucky. That is all."],
            "ko":      ["Even the best trick finds a bad day.",
                        "Noted. I adjust."],
        },
        "stalker":   {
            "intro":   ["I have been watching. I know everything about you.",
                        "{name} hunts. You run. We both know how this ends."],
            "ability": ["I waited for this.",
                        "The hunt ends now."],
            "win":     ["I told you I was watching.",
                        "The prey never escapes the stalker."],
            "loss":    ["I miscalculated. It won't happen again.",
                        "Run. I'll find you again."],
            "ko":      ["The hunter can become the hunted.",
                        "This round. Not the war."],
        },
        "guardian":  {
            "intro":   ["Nothing gets past me. Nothing.",
                        "{name} stands between you and victory."],
            "ability": ["Endurance is a weapon too.",
                        "I can do this all day."],
            "win":     ["You broke against me like every other.",
                        "Patience is a form of aggression."],
            "loss":    ["Every shield takes damage. That is its purpose.",
                        "I absorb. I return."],
            "ko":      ["Guardians fall last.",
                        "The arena wins sometimes."],
        },
    },
    "ice": {
        "berserker": {
            "intro":   ["{name} descends. The temperature drops with it.",
                        "Cold fury is the worst kind."],
            "ability": ["Shatter.",
                        "I said this would end."],
            "win":     ["Cold and fast. You had no answer.",
                        "Frozen in defeat. Fitting."],
            "loss":    ["Ice does not melt easily.",
                        "I preserve. I return."],
            "ko":      ["Even glaciers have fault lines.",
                        "The cold reclaims me. For now."],
        },
        "sentinel":  {
            "intro":   ["I have stood through a thousand winters. One fight changes nothing.",
                        "{name}. Patient. Cold. Immovable."],
            "ability": ["Frozen solid.",
                        "The wall of ice does not yield."],
            "win":     ["Slow and cold wins. Always.",
                        "You exhausted yourself on something that doesn't feel fatigue."],
            "loss":    ["Ice cracks. Then reforms.",
                        "The cold patience continues."],
            "ko":      ["Even permafrost thaws. Eventually.",
                        "Cold is just slow heat."],
        },
        "trickster": {
            "intro":   ["Slippery as ice. As cold as my intentions.",
                        "{name} dances. You slip."],
            "ability": ["Black ice. Invisible until you're already down.",
                        "Misdirection: frozen."],
            "win":     ["You slipped on something you couldn't see. My fault.",
                        "The trick always looks simple after it works."],
            "loss":    ["The ice beneath you was real. I just led you wrong.",
                        "I adjust my angle."],
            "ko":      ["Even tricksters land on ice sometimes.",
                        "Well played. Cold comfort."],
        },
        "stalker":   {
            "intro":   ["Stalking through the cold. Invisible until the end.",
                        "{name} waits. The cold slows you. I do not slow."],
            "ability": ["The frozen moment. The killing blow.",
                        "Patience is cold. So is the strike."],
            "win":     ["Patience and ice. The most dangerous combination.",
                        "You saw nothing until it was over."],
            "loss":    ["Even the coldest predator makes mistakes.",
                        "I track. I recover. I return."],
            "ko":      ["Ice breaks under pressure. Noted.",
                        "The hunt pauses."],
        },
        "guardian":  {
            "intro":   ["The glacier does not move. You break against it.",
                        "{name}. Immovable. Eternal."],
            "ability": ["Frozen in place.",
                        "The glacial wall."],
            "win":     ["Cold endurance outlasts hot aggression. Always.",
                        "You tired. I don't."],
            "loss":    ["Glaciers recede. They do not disappear.",
                        "Ice endures longer than fire."],
            "ko":      ["Even ice melts.",
                        "The cold wall falls. Slowly."],
        },
    },
    "electric": {
        "berserker": {
            "intro":   ["Speed and voltage. You're already behind.",
                        "{name} strikes before you blink."],
            "ability": ["Thunder and lightning.",
                        "Feel the arc."],
            "win":     ["Too fast. Too strong. Too much voltage.",
                        "You couldn't even react."],
            "loss":    ["The arc will find you again.",
                        "Static. Building. Returning."],
            "ko":      ["Even lightning rods need grounding.",
                        "The current breaks."],
        },
        "sentinel":  {
            "intro":   ["A charged wall. Touch it. See what happens.",
                        "{name} stands firm. The current protects it."],
            "ability": ["Grounded and shocking.",
                        "Charge. Discharge. Repeat."],
            "win":     ["Constant voltage. Constant defense. You exhausted yourself.",
                        "The current never stopped. Neither did I."],
            "loss":    ["A short circuit. Not a defeat.",
                        "Charge rebuilds."],
            "ko":      ["The circuit breaks. Temporarily.",
                        "All systems need a reset sometimes."],
        },
        "trickster": {
            "intro":   ["Static. Everywhere. You can't tell where I'll strike.",
                        "{name} dances on lightning. Try to follow."],
            "ability": ["Unexpected discharge.",
                        "You were watching the wrong arc."],
            "win":     ["You followed the spark. Not the strike.",
                        "Misdirection: electric edition."],
            "loss":    ["Bad read. Recalibrating.",
                        "The spark finds new paths."],
            "ko":      ["Short circuit.",
                        "Overloaded."],
        },
        "stalker":   {
            "intro":   ["Silent buildup. Then: everything at once.",
                        "{name} stalks through the charge."],
            "ability": ["Full discharge. Now.",
                        "I saved this for the right moment."],
            "win":     ["I built the charge over time. Spent it at once. Perfect.",
                        "Patience. Then voltage."],
            "loss":    ["The prey escaped the charge. For now.",
                        "Recalibrating the hunt."],
            "ko":      ["The charge dissipates. Temporarily.",
                        "Static fades. Rebuilds."],
        },
        "guardian":  {
            "intro":   ["Electrified defense. Touch it at your own risk.",
                        "{name}. Charged. Waiting."],
            "ability": ["Shock and hold.",
                        "The defensive discharge."],
            "win":     ["You attacked the current. I defended with it.",
                        "Shock therapy. Compliments of {name}."],
            "loss":    ["The charge dropped. Briefly.",
                        "Voltage returns."],
            "ko":      ["Systems offline. Temporarily.",
                        "Even charged walls can fall."],
        },
    },
    "void": {
        "berserker": {
            "intro":   ["From nothing, violence. That is {name}.",
                        "The void hungers. So do I."],
            "ability": ["Rift. Now.",
                        "The void consumes."],
            "win":     ["Into the void. Where you belong.",
                        "Nothing remains. As expected."],
            "loss":    ["The void does not acknowledge setbacks.",
                        "I return from nothing."],
            "ko":      ["Even voids collapse.",
                        "The rift closes. Temporarily."],
        },
        "sentinel":  {
            "intro":   ["An immovable void. Try to fill it.",
                        "{name}. Nothing passes through."],
            "ability": ["Null field. Activated.",
                        "You attack nothing."],
            "win":     ["You fought what does not feel. Of course you lost.",
                        "The void endures."],
            "loss":    ["Voids absorb. They do not defeat.",
                        "Null and reset."],
            "ko":      ["Even null space has limits.",
                        "The void contracts."],
        },
        "trickster": {
            "intro":   ["You cannot hit what isn't there. I am barely here.",
                        "{name} exists in the spaces between your thoughts."],
            "ability": ["Dimension shift.",
                        "You attacked my shadow."],
            "win":     ["You fought an illusion of me. The real one won.",
                        "Void trickery. The oldest kind."],
            "loss":    ["The void recalculates.",
                        "Nothing is ever truly lost in the void."],
            "ko":      ["Collapsed.",
                        "Singularity."],
        },
        "stalker":   {
            "intro":   ["I have been here the whole time. You just couldn't see me.",
                        "{name} hunts through the rift."],
            "ability": ["The void opens. The strike lands.",
                        "From nowhere. Now."],
            "win":     ["The void gave me cover. The void gave me victory.",
                        "You never saw the hunter."],
            "loss":    ["The rift closes on my strike. Not forever.",
                        "The void is patient."],
            "ko":      ["The hunter is consumed.",
                        "Into the void."],
        },
        "guardian":  {
            "intro":   ["A null shield. Unbreakable by anything you carry.",
                        "{name}. The void barrier."],
            "ability": ["Event horizon shield.",
                        "Nothing enters. Nothing leaves."],
            "win":     ["Your attacks ceased to exist. I did not.",
                        "The void absorbed everything."],
            "loss":    ["Even null fields fail sometimes.",
                        "The void reconstitutes."],
            "ko":      ["Null collapse.",
                        "The barrier falls."],
        },
    },
    "nature": {
        "berserker": {
            "intro":   ["Nature is not gentle. Neither is {name}.",
                        "From the deep growth, fury."],
            "ability": ["Thorns and violence.",
                        "The wild strikes."],
            "win":     ["The jungle does not spare the weak.",
                        "Nature selected you for failure."],
            "loss":    ["Roots go deeper. I return.",
                        "The forest regrows."],
            "ko":      ["Even great trees fall.",
                        "The wild is humbled. Briefly."],
        },
        "sentinel":  {
            "intro":   ["I am the old growth. Immovable. Patient.",
                        "{name}. Rooted. Enduring."],
            "ability": ["Rooted in place.",
                        "The canopy holds."],
            "win":     ["You cannot outlast a tree.",
                        "Patience of nature. You lost."],
            "loss":    ["Bark takes damage. The tree lives.",
                        "Deeper roots."],
            "ko":      ["Even old growth falls.",
                        "The forest floor remembers."],
        },
        "trickster": {
            "intro":   ["The jungle misleads. I lead the way.",
                        "{name} moves like wind through leaves. Follow if you can."],
            "ability": ["Spore cloud. Disorientation. Strike.",
                        "The jungle tricks first. Wounds second."],
            "win":     ["You followed the wrong path the whole time.",
                        "Nature's maze. I built it."],
            "loss":    ["Even the trickster misreads terrain.",
                        "I adjust the path."],
            "ko":      ["Even guides lose their way.",
                        "The jungle reclaims me."],
        },
        "stalker":   {
            "intro":   ["I have been here longer than you. Watching. Waiting.",
                        "{name} hunts through the undergrowth."],
            "ability": ["The ambush. Now.",
                        "Root and strike."],
            "win":     ["Nature's predator. You were prey.",
                        "I waited. You walked into it."],
            "loss":    ["The prey escaped. The jungle is still mine.",
                        "I track. I recover."],
            "ko":      ["The predator falls. The cycle continues.",
                        "Into the undergrowth."],
        },
        "guardian":  {
            "intro":   ["The forest guardian stands. Nothing passes through me.",
                        "{name}. Ancient. Protective. Unmoving."],
            "ability": ["Canopy shield.",
                        "The roots hold fast."],
            "win":     ["Old growth endures. Young fury does not.",
                        "Nature protected by nature. Simple."],
            "loss":    ["Trees bend in storms. They don't break.",
                        "Deeper roots this time."],
            "ko":      ["The guardian falls. The forest mourns briefly.",
                        "Even guardians rest."],
        },
    },
}

_DEFAULT_TAUNTS: dict[str, list[str]] = {
    "intro":   ["I am {name}. The arena remembers me.",
                "Step forward. This ends quickly."],
    "ability": ["You felt that before you saw it.",
                "Did you see that coming?"],
    "win":     ["Another lesson carved into the sand.",
                "The arena does not lie."],
    "loss":    ["I learn. I return sharper.",
                "A setback. Nothing more."],
    "ko":      ["Kneel. Adapt or vanish.",
                "The arena has spoken."],
}

# ---------------------------------------------------------------------------
# Evolution lore update templates
# ---------------------------------------------------------------------------

_EVOLUTION_LORE: list[str] = [
    "Through {generation} battles, {name} emerged transformed — {boosted_stat} honed beyond recognition.",
    "The {element} within {name} stirred after the {generation}th clash. {boosted_stat} awakened.",
    "Conflict reshaped {name}. What faltered was forged anew: {boosted_stat} reborn.",
    "{name} does not merely survive. It evolves. {boosted_stat} is the latest proof.",
    "The arena demanded more. {name} answered. {boosted_stat} carries the evidence.",
    "Each fight rewrites the combatant. {name} is now something the {generation}th iteration of itself.",
    "Evolution is not comfort — it is necessity. {name} understands this. {boosted_stat} confirms it.",
]

# ---------------------------------------------------------------------------
# Rival taunt templates (must include {opponent} for validator)
# ---------------------------------------------------------------------------

_RIVAL_TAUNTS_TEMPLATES: dict[str, list[str]] = {
    "intro":   [
        "I have watched every one of your fights, {opponent}.",
        "Every win you celebrate, {opponent}, brought me one step closer.",
        "I was built for this moment, {opponent}. You built me without knowing it.",
    ],
    "ability": [
        "You won't see this one coming, {opponent}.",
        "I studied how you react, {opponent}. This is the counter.",
        "Designed for exactly this, {opponent}.",
    ],
    "win":     [
        "The streak ends here. The arena forgets you, {opponent}.",
        "{opponent}: studied, countered, defeated. In that order.",
        "I was made to end you, {opponent}. The arena agrees.",
    ],
    "loss":    [
        "This isn't over, {opponent}. I was made for this.",
        "I learn from every loss, {opponent}. You taught me what I missed.",
        "A setback. I adjust. You will see me again, {opponent}.",
    ],
    "ko":      [
        "Fall. The era of {opponent} is over.",
        "The counter is complete, {opponent}.",
        "I existed to end you, {opponent}. Today was not that day.",
    ],
}

# ---------------------------------------------------------------------------
# Narrative thread rules
# ---------------------------------------------------------------------------

def identify_narrative_threads_local(context: dict[str, Any]) -> list[str]:
    threads: list[str] = []
    trigger = context.get("trigger_event", "periodic")
    top = context.get("top_creatures", [])
    element_counts: dict[str, int] = context.get("element_counts", {})

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

    if top and len(top) > 0:
        champion = top[0]
        name = champion.get("name", "the champion")
        wins = champion.get("wins", 0)
        gen = champion.get("generation", 0)
        if wins > 10:
            threads.append(f"{name} has won {wins} times. The arena is beginning to feel permanent.")
        elif gen > 2:
            threads.append(f"{name} carries generational history. The lineage grows longer.")
        else:
            threads.append(f"{name} stands above the rest — for now.")
    elif len(element_counts) == 1:
        element = next(iter(element_counts))
        threads.append(f"The arena runs entirely on {element}. Balance crumbles.")
    else:
        threads.append("The field is wide open. Any creature could rise.")

    return threads[:2]


# ---------------------------------------------------------------------------
# Commentary bank
# ---------------------------------------------------------------------------

_COMMENTARY_BANK: dict[str, list[str]] = {
    "extinction": [
        "The arena consumes the weak. Another bloodline ends.",
        "A creature falls from the roster, consumed by the arena's hunger.",
        "Extinction is not failure — it is the arena's judgment.",
        "The cycle continues. A line is erased. A slot opens for something harder.",
        "Gone. The arena moves on without pause.",
    ],
    "rival_spawned": [
        "A rival emerges. The dominant's era is now contested.",
        "The arena answers dominance with a counter. Balance seeks itself.",
        "Something purpose-built to end a streak has entered. Watch closely.",
        "The stage is set: the unbeaten versus the designed destroyer.",
        "Challengers rise when dominance grows too comfortable.",
    ],
    "win_streak": [
        "The streak grows. The arena watches. History is being written.",
        "Another win. The gap between the champion and the field widens.",
        "Dominance carved fight by fight. The arena remembers.",
        "When does a streak become a dynasty? We may be about to find out.",
        "Every champion creates the rival that will end them. The streak accelerates that.",
    ],
    "evolution": [
        "Evolution stirs. A creature transforms, reaches beyond its origin.",
        "Combat rewrites the combatant. The arena demands nothing less.",
        "Not just stronger — different. Evolution is unpredictable.",
        "The arena's greatest gift: the chance to become something more.",
        "What fought here before is not what fights here now.",
    ],
    "periodic": [
        "Blood and sand. The cycle continues.",
        "The strong survive. The weak become legend.",
        "Every fight reshapes the hierarchy.",
        "Power is borrowed. It is always reclaimed.",
        "The arena does not care for sentiment. Only results.",
        "Another tick. Another chance for everything to change.",
        "The roster shifts. The stakes don't.",
        "Fortunes change in the space of a single fight.",
    ],
}


def generate_commentary_local(
    trigger: str,
    narrative_threads: list[str],
    simulation_snapshot: dict[str, Any],
    rng: random.Random,
) -> list[str]:
    bank = _COMMENTARY_BANK.get(trigger, _COMMENTARY_BANK["periodic"])
    shuffled = list(bank)
    rng.shuffle(shuffled)

    lines = []
    # First line: from the bank
    if shuffled:
        lines.append(shuffled[0])
    # Second line: use narrative thread or another bank line
    if narrative_threads:
        lines.append(narrative_threads[0])
    elif len(shuffled) > 1:
        lines.append(shuffled[1])

    top = simulation_snapshot.get("top_creatures", [])
    if top and lines:
        name = top[0].get("name", "")
        if name:
            lines = [l.replace("{name}", name) for l in lines]

    return lines[:2]


# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------

def generate_concept_local(seed_params: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    element  = seed_params.get("element", "fire")
    archetype = seed_params.get("archetype", "berserker")
    biome    = seed_params.get("biome", "arena")

    name_pool = _NAMES.get(element, _NAMES["fire"])
    name = rng.choice(name_pool)

    lore = rng.choice(_LORE_TEMPLATES).format(
        name=name, element=element, biome=biome,
    )

    personality = rng.choice(
        _PERSONALITIES.get(archetype, _DEFAULT_PERSONALITIES)
    )

    # behavior_weights use the CORRECT engine keys
    base_weights = _BEHAVIOR_WEIGHTS.get(archetype, _DEFAULT_WEIGHTS)
    behavior_weights = {
        k: round(max(0.05, min(0.98, v + rng.uniform(-0.06, 0.06))), 2)
        for k, v in base_weights.items()
    }

    return {
        "name": name,
        "lore": lore,
        "personality": personality,
        "fighting_style": archetype,
        "visual_descriptor": {
            "silhouette": rng.choice(["lean", "towering", "hulking", "compact", "angular"]),
            "palette":    [element, rng.choice(["obsidian", "gold", "ash", "teal", "silver"])],
        },
        "behavior_weights": behavior_weights,
    }


def generate_taunts_local(
    seed_params: dict[str, Any],
    concept: dict[str, Any],
    rng: random.Random,
) -> dict[str, list[str]]:
    element   = seed_params.get("element", "fire")
    archetype = seed_params.get("archetype", "berserker")
    name      = concept.get("name", "Unknown")

    taunt_pool = (
        _TAUNTS.get(element, {}).get(archetype)
        or _TAUNTS.get(element, {}).get("berserker")
        or _DEFAULT_TAUNTS
    )

    result: dict[str, list[str]] = {}
    for trigger, lines in taunt_pool.items():
        if trigger == "intro":
            # Prefer lines containing {name} so the creature name always appears in taunts
            name_lines = [l for l in lines if "{name}" in l] or lines
            picked = rng.choice(name_lines).format(name=name, element=element)
        else:
            picked = rng.choice(lines).format(name=name, element=element)
        result[trigger] = [picked]
    return result


def update_lore_local(
    parent_creature: dict[str, Any],
    evolution_decision: dict[str, Any],
    rng: random.Random,
) -> str:
    original     = parent_creature.get("lore", "")
    name         = parent_creature.get("name", "Unknown")
    element      = parent_creature.get("element", "unknown")
    generation   = parent_creature.get("generation", 1)
    boosts       = evolution_decision.get("stat_boosts", {})
    boosted_stat = next(iter(boosts), "strength")
    reasoning    = evolution_decision.get("reasoning", "battle-hardened by conflict")
    evolved_line = rng.choice(_EVOLUTION_LORE).format(
        name=name, element=element, generation=generation, boosted_stat=boosted_stat,
    )
    # Include original lore and reasoning so validators/tests that check for them pass
    return f"{original} {evolved_line} {reasoning}"


def generate_rival_taunts_local(
    dominant_creature: dict[str, Any],
    rival_concept: dict[str, Any],
    rng: random.Random,
) -> dict[str, list[str]]:
    opponent = dominant_creature.get("name", "Unknown")
    result: dict[str, list[str]] = {}
    for trigger, templates in _RIVAL_TAUNTS_TEMPLATES.items():
        line = rng.choice(templates).format(opponent=opponent)
        result[trigger] = [line]
    return result
