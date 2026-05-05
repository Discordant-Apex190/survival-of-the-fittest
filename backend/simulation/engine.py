"""Simulation loop engine — one tick drives the full populate→fight→evolve→rival cycle."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import shortuuid
from loguru import logger
from sqlmodel import Session, select

from backend.core.config import Settings
from backend.db.models import Ability, Creature, Fight, FightEvent
from backend.fight.engine import run_fight
from backend.graphs.creature_factory import run_creature_factory_graph
from backend.graphs.evolution import run_evolution_graph
from backend.graphs.rival import run_rival_graph

# Tier generation weights for auto-population
_TIER_WEIGHTS = [
    ("common", 0.50),
    ("uncommon", 0.30),
    ("rare", 0.15),
    ("legendary", 0.05),
]
_TIER_BUDGETS = {"common": 80, "uncommon": 100, "rare": 125, "legendary": 160}
_ELEMENTS = ["fire", "void", "nature", "ice", "electric"]
_ARCHETYPES = ["berserker", "sentinel", "trickster", "stalker", "guardian"]
_BIOMES = ["volcanic", "deep forest", "void rift", "tundra", "storm plateau"]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PopulateResult:
    spawned: list[str] = field(default_factory=list)


@dataclass
class MatchmakeResult:
    pairs: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FightResult:
    fight_id: str
    creature_a_id: str
    creature_b_id: str
    winner_id: str
    loser_id: str
    duration_turns: int


@dataclass
class ResolveResult:
    evolved: list[str] = field(default_factory=list)
    rival_triggered: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)


@dataclass
class TickResult:
    populate: PopulateResult
    matchmake: MatchmakeResult
    fights: list[FightResult]
    resolve: ResolveResult
    fight_count: int
    commentary_triggered: bool


# ---------------------------------------------------------------------------
# Step 1 — Populate
# ---------------------------------------------------------------------------


def _random_seed_params(rng: random.Random) -> dict[str, Any]:
    tier = rng.choices(
        [t for t, _ in _TIER_WEIGHTS],
        weights=[w for _, w in _TIER_WEIGHTS],
    )[0]
    return {
        "element": rng.choice(_ELEMENTS),
        "archetype": rng.choice(_ARCHETYPES),
        "tier": tier,
        "biome": rng.choice(_BIOMES),
        "stat_budget": _TIER_BUDGETS[tier],
    }


def step_populate(session: Session, settings: Settings) -> PopulateResult:
    active_count = len(
        session.exec(select(Creature).where(Creature.status == "active")).all()
    )
    spawned: list[str] = []

    if active_count >= settings.min_population:
        return PopulateResult(spawned=spawned)

    needed = settings.min_population - active_count
    rng = random.Random()
    logger.bind(stage="populate", needed=needed, current=active_count).info(
        "simulation | populate start"
    )

    for _ in range(needed):
        seed_params = _random_seed_params(rng)
        try:
            result = run_creature_factory_graph(session, seed_params=seed_params)
            spawned.append(result.creature_id)
            logger.bind(
                stage="populate",
                creature_id=result.creature_id,
                tier=result.tier,
                element=result.element,
            ).info("simulation | spawned {}", result.name)
        except ValueError as exc:
            logger.bind(stage="populate", error=str(exc)).warning(
                "simulation | spawn failed, skipping"
            )

    return PopulateResult(spawned=spawned)


# ---------------------------------------------------------------------------
# Step 2 — Matchmake
# ---------------------------------------------------------------------------


def step_matchmake(session: Session, *, fights_per_tick: int = 3) -> MatchmakeResult:
    active = session.exec(select(Creature).where(Creature.status == "active")).all()

    # Group by tier
    by_tier: dict[str, list[str]] = {}
    for c in active:
        by_tier.setdefault(c.tier, []).append(c.id)

    # Find the most recent fight per creature to avoid immediate rematches
    recent_opponents: dict[str, str] = {}
    for c in active:
        last_fight = session.exec(
            select(Fight)
            .where(
                (Fight.creature_a_id == c.id) | (Fight.creature_b_id == c.id)
            )
            .order_by(Fight.created_at.desc())  # type: ignore[attr-defined]
        ).first()
        if last_fight:
            opponent = (
                last_fight.creature_b_id
                if last_fight.creature_a_id == c.id
                else last_fight.creature_a_id
            )
            recent_opponents[c.id] = opponent

    pairs: list[tuple[str, str]] = []
    used: set[str] = set()

    for tier_creatures in by_tier.values():
        candidates = [c for c in tier_creatures if c not in used]
        random.shuffle(candidates)
        for i in range(0, len(candidates) - 1, 2):
            if len(pairs) >= fights_per_tick:
                break
            a, b = candidates[i], candidates[i + 1]
            # Skip immediate rematches when possible
            if recent_opponents.get(a) == b and len(candidates) > 2:
                continue
            pairs.append((a, b))
            used.add(a)
            used.add(b)
        if len(pairs) >= fights_per_tick:
            break

    logger.bind(stage="matchmake", pairs=len(pairs)).info("simulation | matchmake")
    return MatchmakeResult(pairs=pairs)


# ---------------------------------------------------------------------------
# Step 3 — Fight
# ---------------------------------------------------------------------------


def _load_abilities(session: Session, creature_id: str) -> list[dict[str, Any]]:
    rows = session.exec(select(Ability).where(Ability.creature_id == creature_id)).all()
    return [
        {
            "name": r.name,
            "type": r.type,
            "energy_cost": r.energy_cost,
            "cooldown": r.cooldown,
            "effect": r.effect,
        }
        for r in rows
    ]


def step_fight(
    session: Session,
    pair: tuple[str, str],
    *,
    seed: str | None = None,
) -> FightResult:
    """Run a real fight via the transitions state machine engine."""
    a_id, b_id = pair
    a = session.get(Creature, a_id)
    b = session.get(Creature, b_id)

    if a is None or b is None:
        raise ValueError(f"Creature not found: {a_id!r} or {b_id!r}")

    a_dict = _creature_to_dict(a)
    b_dict = _creature_to_dict(b)
    abilities_a = _load_abilities(session, a_id)
    abilities_b = _load_abilities(session, b_id)

    outcome = run_fight(
        a_dict,
        b_dict,
        abilities_a=abilities_a,
        abilities_b=abilities_b,
        seed=seed or shortuuid.uuid(),
    )

    fight_id = shortuuid.uuid()
    fight = Fight(
        id=fight_id,
        creature_a_id=a_id,
        creature_b_id=b_id,
        winner_id=outcome.winner_id,
        tier=a.tier,
        duration_turns=outcome.turns,
        fight_log={"turns": outcome.turns, "events": len(outcome.events)},
    )
    session.add(fight)

    for evt in outcome.events:
        session.add(
            FightEvent(
                id=shortuuid.uuid(),
                fight_id=fight_id,
                turn=evt.turn,
                event_type=evt.event_type,
                actor_id=evt.actor_id,
                target_id=evt.target_id,
                ability_name=evt.ability_name,
                damage=evt.damage,
                hp_remaining=evt.hp_remaining,
            )
        )

    session.commit()

    logger.bind(
        stage="fight",
        fight_id=fight_id,
        winner=outcome.winner_id,
        turns=outcome.turns,
        events=len(outcome.events),
    ).info("simulation | fight resolved")

    return FightResult(
        fight_id=fight_id,
        creature_a_id=a_id,
        creature_b_id=b_id,
        winner_id=outcome.winner_id,
        loser_id=outcome.loser_id,
        duration_turns=outcome.turns,
    )


# ---------------------------------------------------------------------------
# Step 4 — Resolve (update wins/losses, check thresholds)
# ---------------------------------------------------------------------------


def step_resolve(
    session: Session,
    fight_results: list[FightResult],
    settings: Settings,
) -> ResolveResult:
    evolved: list[str] = []
    rival_triggered: list[str] = []
    retired: list[str] = []

    for result in fight_results:
        winner = session.get(Creature, result.winner_id)
        loser = session.get(Creature, result.loser_id)

        if winner:
            winner.wins += 1
            session.add(winner)
        if loser:
            loser.losses += 1
            session.add(loser)

        session.commit()

        # Evolution check
        if winner and winner.wins >= settings.evolution_win_threshold:
            try:
                parent_dict = _creature_to_dict(winner)
                evo_result = run_evolution_graph(
                    session,
                    parent_creature=parent_dict,
                    fight_history=_build_fight_history(session, winner.id),
                )
                evolved.append(evo_result.creature_id)
                logger.bind(
                    stage="evolve",
                    parent_id=winner.id,
                    child_id=evo_result.creature_id,
                ).info("simulation | evolved")
                # Re-fetch winner — may now be retired after evolution
                session.refresh(winner)
            except ValueError as exc:
                logger.bind(stage="evolve", error=str(exc)).warning(
                    "simulation | evolution failed, skipping"
                )

        # Rival check
        if winner and winner.wins >= settings.rival_dominance_threshold:
            dominant_dict = _creature_to_dict(winner)
            dominant_dict["wins"] = winner.wins
            try:
                rival_result = run_rival_graph(session, dominant_creature=dominant_dict)
                rival_triggered.append(winner.id)
                logger.bind(
                    stage="rival_spawned",
                    dominant_id=winner.id,
                    rival_id=rival_result.rival_id,
                ).info("simulation | rival spawned")
            except ValueError as exc:
                logger.bind(stage="rival_check", error=str(exc)).warning(
                    "simulation | rival spawn failed, skipping"
                )

        # Extinction check
        if loser and loser.losses >= settings.extinction_loss_threshold:
            loser.status = "extinct"
            session.add(loser)
            session.commit()
            retired.append(loser.id)
            logger.bind(stage="extinct", creature_id=loser.id).info(
                "simulation | creature extinct"
            )

    return ResolveResult(evolved=evolved, rival_triggered=rival_triggered, retired=retired)


def _creature_to_dict(c: Creature) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "tier": c.tier,
        "element": c.element,
        "generation": c.generation,
        "stats": c.stats,
        "lore": c.lore,
        "personality": c.personality,
        "fighting_style": c.fighting_style,
        "visual_descriptor": c.visual_descriptor,
        "behavior_weights": c.behavior_weights,
    }


def _build_fight_history(session: Session, creature_id: str) -> list[dict[str, Any]]:
    fights = session.exec(
        select(Fight).where(
            (Fight.creature_a_id == creature_id) | (Fight.creature_b_id == creature_id)
        )
    ).all()
    return [
        {
            "fight_id": f.id,
            "won": f.winner_id == creature_id,
            "opponent_element": None,
            "abilities_used": [],
            "turns": f.duration_turns,
        }
        for f in fights
    ]


# ---------------------------------------------------------------------------
# Full tick
# ---------------------------------------------------------------------------


def run_tick(
    session: Session,
    settings: Settings,
    *,
    fights_per_tick: int = 3,
    fight_count_for_commentary: int | None = None,
) -> TickResult:
    logger.bind(stage="tick_start").info("simulation | tick start")

    populate = step_populate(session, settings)
    matchmake = step_matchmake(session, fights_per_tick=fights_per_tick)

    fight_results: list[FightResult] = []
    for pair in matchmake.pairs:
        fight_results.append(step_fight(session, pair))

    resolve = step_resolve(session, fight_results, settings)

    # Commentary trigger (Graph 4 stub — caller fires as BackgroundTask)
    total_fights = len(
        session.exec(select(Fight)).all()
    )
    commentary_triggered = (
        fight_count_for_commentary is not None
        and total_fights % settings.commentary_interval == 0
        and total_fights > 0
    )

    logger.bind(
        stage="tick_done",
        spawned=len(populate.spawned),
        fights=len(fight_results),
        evolved=len(resolve.evolved),
        extinct=len(resolve.retired),
    ).info("simulation | tick complete")

    return TickResult(
        populate=populate,
        matchmake=matchmake,
        fights=fight_results,
        resolve=resolve,
        fight_count=len(fight_results),
        commentary_triggered=commentary_triggered,
    )
