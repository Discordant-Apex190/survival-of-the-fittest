"""Behavior tree for fight action selection.

Replaces the probabilistic choose_action() in CombatantMachine with a
structured tree that encodes tactical priorities. All state flows through
BTContext so the tree itself is stateless and can be a module-level singleton.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Context passed into each tick
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BTContext:
    hp_ratio:        float
    enemy_hp_ratio:  float
    aggression:      float
    caution:         float
    cunning:         float
    risk_tolerance:  float
    momentum:        int
    has_ability:     bool
    energy:          int
    flee_bait_active: bool
    rng:             random.Random


# ---------------------------------------------------------------------------
# Node base and leaf types
# ---------------------------------------------------------------------------

# Each tick returns (success: bool, action: str | None)
_Result = tuple[bool, str | None]


class BTNode:
    def tick(self, ctx: BTContext) -> _Result:
        raise NotImplementedError


class Sequence(BTNode):
    """AND — all children must succeed; propagates the first non-None action."""
    def __init__(self, *children: BTNode) -> None:
        self.children = children

    def tick(self, ctx: BTContext) -> _Result:
        action: str | None = None
        for child in self.children:
            ok, act = child.tick(ctx)
            if not ok:
                return False, None
            if act is not None:
                action = act
        return True, action


class Selector(BTNode):
    """OR — returns the first successful child."""
    def __init__(self, *children: BTNode) -> None:
        self.children = children

    def tick(self, ctx: BTContext) -> _Result:
        for child in self.children:
            ok, act = child.tick(ctx)
            if ok:
                return True, act
        return False, None


class Condition(BTNode):
    def __init__(self, fn: Callable[[BTContext], bool]) -> None:
        self.fn = fn

    def tick(self, ctx: BTContext) -> _Result:
        return self.fn(ctx), None


class Action(BTNode):
    def __init__(self, result: str) -> None:
        self.result = result

    def tick(self, ctx: BTContext) -> _Result:
        return True, self.result


class Inverter(BTNode):
    def __init__(self, child: BTNode) -> None:
        self.child = child

    def tick(self, ctx: BTContext) -> _Result:
        ok, act = self.child.tick(ctx)
        return not ok, act


class Probability(BTNode):
    """Succeeds with probability p (or p(ctx) if callable)."""
    def __init__(self, p: float | Callable[[BTContext], float]) -> None:
        self._p_fn: Callable[[BTContext], float] = p if callable(p) else (lambda _: p)

    def tick(self, ctx: BTContext) -> _Result:
        return ctx.rng.random() < self._p_fn(ctx), None


# ---------------------------------------------------------------------------
# Fight decision tree
# ---------------------------------------------------------------------------

FIGHT_TREE: BTNode = Selector(
    # --- RageIfLowHP: if low HP and aggressive, go berserk ---
    Sequence(
        Condition(lambda ctx: ctx.hp_ratio < 0.30),
        Condition(lambda ctx: ctx.aggression > 0.60),
        Action("rage"),
    ),

    # --- KillShot: if enemy is nearly dead and we have an ability, use it ---
    Sequence(
        Condition(lambda ctx: ctx.enemy_hp_ratio < 0.20),
        Condition(lambda ctx: ctx.has_ability),
        Action("ability"),
    ),

    # --- FleeToCounter: cunning creature bails at low HP to set up counter ---
    Sequence(
        Condition(lambda ctx: ctx.hp_ratio < 0.30),
        Condition(lambda ctx: ctx.cunning > 0.50),
        Inverter(Condition(lambda ctx: ctx.flee_bait_active)),
        Action("flee"),
    ),

    # --- MomentumPress: maintain a streak with abilities ---
    Sequence(
        Condition(lambda ctx: ctx.momentum >= 3),
        Condition(lambda ctx: ctx.has_ability),
        Action("ability"),
    ),

    # --- DefendIfCautious: cautious creatures protect their HP ---
    Sequence(
        Condition(lambda ctx: ctx.caution > 0.60),
        Probability(lambda ctx: ctx.caution * 0.50),
        Action("defend"),
    ),

    # --- EnergyConserve: low-energy risk-averse creatures play safe ---
    Sequence(
        Condition(lambda ctx: ctx.energy < 15),
        Condition(lambda ctx: ctx.risk_tolerance < 0.40),
        Action("defend"),
    ),

    # --- TauntPress: cunning creatures use taunts to build momentum ---
    Sequence(
        Condition(lambda ctx: ctx.cunning > 0.40),
        Probability(0.15),
        Action("taunt"),
    ),

    # --- Default ---
    Action("attack"),
)
