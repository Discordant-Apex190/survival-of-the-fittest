"""Real fight engine — turn-based combat with transitions state machine.

Each combatant runs its own state machine:
    Idle → Engage → [Attack | Defend | Flee | Rage]
                 ↑__________________________________|

Turn flow:
  1. Both combatants independently pick an action (state-driven + behavior weights).
  2. Action pair resolves into damage for each side.
  3. HP updates, momentum tracks consecutive hits.
  4. State transitions fire.
  5. FightTurn record captured.
  6. KO check — fight ends when either creature reaches 0 HP or max_turns exceeded.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from loguru import logger
from transitions import Machine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TURNS = 30
MOMENTUM_BONUS = 0.05       # per consecutive hit: +5% damage
LOW_HP_RATIO = 0.30         # below 30% HP → behaviour shifts
ABILITY_ENERGY_REGEN = 10   # energy regenerated per turn


# ---------------------------------------------------------------------------
# State machine definition
# ---------------------------------------------------------------------------

STATES = ["idle", "engage", "attack", "defend", "flee", "rage"]

TRANSITIONS = [
    {"trigger": "start_fight",    "source": "idle",    "dest": "engage"},
    {"trigger": "choose_attack",  "source": "engage",  "dest": "attack"},
    {"trigger": "choose_defend",  "source": "engage",  "dest": "defend"},
    {"trigger": "choose_flee",    "source": "engage",  "dest": "flee"},
    {"trigger": "choose_rage",    "source": "engage",  "dest": "rage"},
    {"trigger": "reset_engage",   "source": ["attack", "defend", "flee", "rage"], "dest": "engage"},
]


class CombatantMachine:
    """Wraps a combatant with a transitions state machine and mutable combat stats."""

    def __init__(
        self,
        creature_id: str,
        stats: dict[str, int],
        behavior_weights: dict[str, Any],
        abilities: list[dict[str, Any]],
        rng: random.Random,
    ) -> None:
        self.creature_id = creature_id
        # Mutable combat stats
        self.max_hp: int = stats.get("health", 20)
        self.hp: int = self.max_hp
        self.attack: int = stats.get("attack", 10)
        self.defense: int = stats.get("defense", 10)
        self.speed: int = stats.get("speed", 10)

        # Behavior weights (0.0–1.0 each, don't need to sum to 1)
        self.aggression: float = float(behavior_weights.get("aggression", 0.5))
        self.caution: float = float(behavior_weights.get("caution", 0.3))
        self.cunning: float = float(behavior_weights.get("cunning", 0.3))
        self.risk_tolerance: float = float(behavior_weights.get("risk_tolerance", 0.4))

        self.abilities = abilities
        self.cooldowns: dict[str, int] = {a["name"]: 0 for a in abilities}
        self.energy: int = 50
        self.momentum: int = 0          # consecutive hits landed
        self.defending: bool = False
        self.flee_bait: bool = False    # cunning flee-then-counter flag
        self.rng = rng

        self.machine = Machine(
            model=self,
            states=STATES,
            transitions=TRANSITIONS,
            initial="idle",
            auto_transitions=False,
        )

    @property
    def hp_ratio(self) -> float:
        return self.hp / self.max_hp

    def is_alive(self) -> bool:
        return self.hp > 0

    def available_abilities(self) -> list[dict[str, Any]]:
        return [
            a for a in self.abilities
            if self.cooldowns.get(a["name"], 0) == 0
            and self.energy >= a.get("energy_cost", 0)
        ]

    def tick_cooldowns(self) -> None:
        for name in self.cooldowns:
            if self.cooldowns[name] > 0:
                self.cooldowns[name] -= 1
        self.energy = min(100, self.energy + ABILITY_ENERGY_REGEN)

    def choose_action(self) -> str:
        """Pick action based on state + behavior weights + HP ratio.

        Returns one of: 'attack', 'ability', 'defend', 'flee', 'rage', 'taunt'
        """
        hp_r = self.hp_ratio
        low_hp = hp_r < LOW_HP_RATIO

        # Build probability weights for each action
        w_attack = 0.40 + self.aggression * 0.20
        w_ability = 0.20 + self.risk_tolerance * 0.10 if self.available_abilities() else 0.0
        w_defend = 0.15 + self.caution * 0.20
        w_flee   = 0.05 + self.cunning * 0.10
        w_rage   = 0.05 + self.risk_tolerance * 0.10
        w_taunt  = 0.05 + self.cunning * 0.05

        # HP pressure adjustments
        if low_hp:
            if self.aggression > 0.6:
                w_rage += 0.25
                w_defend -= 0.05
            else:
                w_defend += 0.15
                w_flee += 0.10
                w_attack -= 0.10

        # Normalise and pick
        choices = ["attack", "ability", "defend", "flee", "rage", "taunt"]
        weights = [max(0.0, w) for w in [w_attack, w_ability, w_defend, w_flee, w_rage, w_taunt]]
        total = sum(weights)
        if total == 0:
            return "attack"
        probs = [w / total for w in weights]
        return self.rng.choices(choices, weights=probs, k=1)[0]


# ---------------------------------------------------------------------------
# Turn event record
# ---------------------------------------------------------------------------


@dataclass
class TurnEvent:
    turn: int
    event_type: str             # attack | ability | dodge | taunt | ko
    actor_id: str
    target_id: str | None
    ability_name: str | None
    damage: int | None
    hp_remaining: dict[str, int]
    notes: str = ""


# ---------------------------------------------------------------------------
# Damage formula
# ---------------------------------------------------------------------------


def compute_damage(
    attacker: CombatantMachine,
    defender: CombatantMachine,
    *,
    ability: dict[str, Any] | None = None,
    is_rage: bool = False,
    is_counter: bool = False,
) -> int:
    """Base damage: max(1, atk - def * 0.4) scaled by momentum + state modifiers."""
    base = max(1.0, attacker.attack - defender.defense * 0.4)
    momentum_mult = 1.0 + MOMENTUM_BONUS * min(attacker.momentum, 5)

    # State modifiers
    if is_rage:
        base *= 1.5
    if is_counter:
        base *= 1.3
    if defender.defending:
        base *= 0.5

    if ability:
        # Ability adds a flat bonus proportional to energy_cost
        base += ability.get("energy_cost", 0) * 0.5

    raw = base * momentum_mult
    return max(1, int(raw))


def compute_win_probability(creature_a: dict[str, Any], creature_b: dict[str, Any]) -> float:
    """Elo-style win probability from the design document."""
    def score(c: dict[str, Any]) -> float:
        s = c.get("stats", {})
        return (
            s.get("attack", 10) * 0.35
            + s.get("defense", 10) * 0.20
            + s.get("speed", 10) * 0.25
            + s.get("health", 10) * 0.20
        )

    sa, sb = score(creature_a), score(creature_b)
    raw = 1 / (1 + 10 ** ((sb - sa) / 40))
    return max(0.05, min(0.95, raw))


# ---------------------------------------------------------------------------
# Core fight runner
# ---------------------------------------------------------------------------


@dataclass
class FightOutcome:
    winner_id: str
    loser_id: str
    turns: int
    events: list[TurnEvent]


def run_fight(
    creature_a: dict[str, Any],
    creature_b: dict[str, Any],
    *,
    abilities_a: list[dict[str, Any]] | None = None,
    abilities_b: list[dict[str, Any]] | None = None,
    seed: str | None = None,
    max_turns: int = MAX_TURNS,
) -> FightOutcome:
    """Run a full fight between two creatures. Returns outcome with full event log."""

    rng = random.Random(seed)
    events: list[TurnEvent] = []

    ca = CombatantMachine(
        creature_a["id"],
        creature_a.get("stats", {}),
        creature_a.get("behavior_weights", {}),
        abilities_a or [],
        random.Random(f"{seed}:a"),
    )
    cb = CombatantMachine(
        creature_b["id"],
        creature_b.get("stats", {}),
        creature_b.get("behavior_weights", {}),
        abilities_b or [],
        random.Random(f"{seed}:b"),
    )

    ca.start_fight()
    cb.start_fight()

    def _hp_snapshot() -> dict[str, int]:
        return {ca.creature_id: ca.hp, cb.creature_id: cb.hp}

    for turn in range(1, max_turns + 1):
        # Speed advantage: faster creature always acts first
        first, second = (ca, cb) if ca.speed >= cb.speed else (cb, ca)

        for attacker, defender in [(first, second), (second, first)]:
            if not attacker.is_alive() or not defender.is_alive():
                break

            action = attacker.choose_action()
            is_rage = action == "rage"
            is_flee_bait = attacker.flee_bait

            attacker.flee_bait = False  # consume bait flag
            defender.defending = False  # reset defend from previous turn

            if action == "defend":
                attacker.choose_defend()
                attacker.defending = True
                events.append(
                    TurnEvent(
                        turn=turn,
                        event_type="dodge",
                        actor_id=attacker.creature_id,
                        target_id=None,
                        ability_name=None,
                        damage=None,
                        hp_remaining=_hp_snapshot(),
                        notes="defending",
                    )
                )
                attacker.reset_engage()
                attacker.momentum = 0
                continue

            if action == "taunt":
                attacker.choose_attack()  # taunt is an attack-adjacent state
                events.append(
                    TurnEvent(
                        turn=turn,
                        event_type="taunt",
                        actor_id=attacker.creature_id,
                        target_id=defender.creature_id,
                        ability_name=None,
                        damage=None,
                        hp_remaining=_hp_snapshot(),
                        notes="taunting",
                    )
                )
                attacker.reset_engage()
                attacker.momentum += 1  # taunts build momentum for the next hit
                continue

            if action == "flee":
                # High-cunning flee is a bait — next attack from this creature deals counter bonus
                if attacker.cunning > 0.5:
                    attacker.flee_bait = True
                attacker.choose_flee()
                events.append(
                    TurnEvent(
                        turn=turn,
                        event_type="dodge",
                        actor_id=attacker.creature_id,
                        target_id=None,
                        ability_name=None,
                        damage=None,
                        hp_remaining=_hp_snapshot(),
                        notes="fleeing" + (" (bait)" if attacker.flee_bait else ""),
                    )
                )
                attacker.reset_engage()
                attacker.momentum = 0
                continue

            # Attack / ability / rage all deal damage
            chosen_ability: dict[str, Any] | None = None
            if action == "ability":
                avail = attacker.available_abilities()
                if avail:
                    chosen_ability = rng.choice(avail)
                    attacker.cooldowns[chosen_ability["name"]] = chosen_ability.get("cooldown", 2)
                    attacker.energy -= chosen_ability.get("energy_cost", 0)
                    attacker.choose_attack()
                else:
                    action = "attack"  # fallback
                    attacker.choose_attack()
            elif is_rage:
                attacker.choose_rage()
            else:
                attacker.choose_attack()

            dmg = compute_damage(
                attacker,
                defender,
                ability=chosen_ability,
                is_rage=is_rage,
                is_counter=is_flee_bait,
            )
            defender.hp = max(0, defender.hp - dmg)
            attacker.momentum += 1

            event_type = "ability" if chosen_ability else "attack"
            events.append(
                TurnEvent(
                    turn=turn,
                    event_type=event_type,
                    actor_id=attacker.creature_id,
                    target_id=defender.creature_id,
                    ability_name=chosen_ability["name"] if chosen_ability else None,
                    damage=dmg,
                    hp_remaining=_hp_snapshot(),
                    notes="rage" if is_rage else ("counter" if is_flee_bait else ""),
                )
            )

            attacker.reset_engage()
            attacker.tick_cooldowns()

            if not defender.is_alive():
                events.append(
                    TurnEvent(
                        turn=turn,
                        event_type="ko",
                        actor_id=attacker.creature_id,
                        target_id=defender.creature_id,
                        ability_name=None,
                        damage=None,
                        hp_remaining=_hp_snapshot(),
                    )
                )
                logger.bind(
                    stage="fight",
                    winner=attacker.creature_id,
                    loser=defender.creature_id,
                    turns=turn,
                ).debug("fight | KO on turn {}", turn)
                return FightOutcome(
                    winner_id=attacker.creature_id,
                    loser_id=defender.creature_id,
                    turns=turn,
                    events=events,
                )

    # Max turns reached — winner is whoever has more HP remaining
    if ca.hp >= cb.hp:
        winner, loser = ca, cb
    else:
        winner, loser = cb, ca

    events.append(
        TurnEvent(
            turn=max_turns,
            event_type="ko",
            actor_id=winner.creature_id,
            target_id=loser.creature_id,
            ability_name=None,
            damage=None,
            hp_remaining=_hp_snapshot(),
            notes="timeout",
        )
    )
    logger.bind(stage="fight", winner=winner.creature_id, turns=max_turns).debug(
        "fight | timeout, winner by HP"
    )
    return FightOutcome(
        winner_id=winner.creature_id,
        loser_id=loser.creature_id,
        turns=max_turns,
        events=events,
    )
