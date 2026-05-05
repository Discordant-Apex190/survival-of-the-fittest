from __future__ import annotations

from collections.abc import Callable
from typing import Any

import shortuuid
from loguru import logger
from sqlmodel import Session, select

from backend.db.models import Ability, Commentary, Creature, Evolution, Taunt


def write_creature_bundle(
    session: Session,
    *,
    seed_params: dict[str, Any],
    concept: dict[str, Any],
    stats: dict[str, int],
    abilities: list[dict[str, Any]],
    taunts: dict[str, list[str]],
) -> str:
    creature_id = shortuuid.uuid()
    creature = Creature(
        id=creature_id,
        name=concept["name"],
        tier=seed_params["tier"],
        element=seed_params["element"],
        stats=stats,
        visual_descriptor=concept["visual_descriptor"],
        behavior_weights=concept["behavior_weights"],
        lore=concept["lore"],
        personality=concept["personality"],
        fighting_style=concept["fighting_style"],
    )
    session.add(creature)

    for ability in abilities:
        session.add(
            Ability(
                id=shortuuid.uuid(),
                creature_id=creature_id,
                name=ability["name"],
                type=ability["type"],
                energy_cost=ability["energy_cost"],
                cooldown=ability["cooldown"],
                effect=ability["effect"],
                description=ability["description"],
            )
        )

    for trigger, lines in taunts.items():
        for line in lines:
            session.add(
                Taunt(
                    id=shortuuid.uuid(),
                    creature_id=creature_id,
                    trigger=trigger,
                    text=line,
                )
            )

    session.commit()
    return creature_id


# ---------------------------------------------------------------------------
# LangGraph node factory
# ---------------------------------------------------------------------------


def make_write_sqlite_node(
    session: Session,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_write_sqlite(state: dict[str, Any]) -> dict[str, Any]:
        creature_id = write_creature_bundle(
            session,
            seed_params=state["seed_params"],
            concept=state["concept"],
            stats=state["stats"],
            abilities=state["abilities"],
            taunts=state["taunts"],
        )
        logger.bind(stage="persisted", creature_id=creature_id).info(
            "creature_factory | persisted"
        )
        return {"creature_id": creature_id}

    return node_write_sqlite


# ---------------------------------------------------------------------------
# Graph 2 — evolution write node
# ---------------------------------------------------------------------------


def make_write_evolution_node(
    session: Session,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_write_evolution(state: dict[str, Any]) -> dict[str, Any]:
        parent_dict = state["parent_creature"]
        parent_id = parent_dict["id"]
        parent = session.get(Creature, parent_id)
        if parent is None:
            raise ValueError(f"parent creature {parent_id} not found in DB")

        decision = state["evolution_decision"]
        boosts: dict[str, int] = decision.get("stat_boosts", {})
        new_stats = {k: v + boosts.get(k, 0) for k, v in parent.stats.items()}
        new_lore = state.get("evolution_updated_lore") or parent.lore

        child_id = shortuuid.uuid()
        child = Creature(
            id=child_id,
            name=parent.name,
            tier=parent.tier,
            element=parent.element,
            generation=parent.generation + 1,
            parent_id=parent.id,
            stats=new_stats,
            visual_descriptor=parent.visual_descriptor,
            behavior_weights=parent.behavior_weights,
            lore=new_lore,
            personality=parent.personality,
            fighting_style=parent.fighting_style,
        )
        session.add(child)

        parent_abilities = session.exec(
            select(Ability).where(Ability.creature_id == parent_id)
        ).all()
        for ab in parent_abilities:
            session.add(
                Ability(
                    id=shortuuid.uuid(),
                    creature_id=child_id,
                    name=ab.name,
                    type=ab.type,
                    energy_cost=ab.energy_cost,
                    cooldown=ab.cooldown,
                    effect=ab.effect,
                    description=ab.description,
                )
            )

        new_ability = state.get("evolution_new_ability")
        if new_ability:
            session.add(
                Ability(
                    id=shortuuid.uuid(),
                    creature_id=child_id,
                    name=new_ability["name"],
                    type=new_ability["type"],
                    energy_cost=new_ability["energy_cost"],
                    cooldown=new_ability["cooldown"],
                    effect=new_ability["effect"],
                    description=new_ability["description"],
                )
            )

        parent.status = "retired"
        session.add(parent)

        evolution_record = Evolution(
            id=shortuuid.uuid(),
            parent_id=parent.id,
            child_id=child_id,
            trigger="win_threshold",
            changes={"stat_boosts": boosts, "new_ability": bool(new_ability)},
            evolution_reasoning=decision.get("reasoning", ""),
        )
        session.add(evolution_record)
        session.commit()

        logger.bind(stage="write_evolution", parent_id=parent_id, child_id=child_id).info(
            "evolution | child persisted"
        )
        return {"creature_id": child_id}

    return node_write_evolution


# ---------------------------------------------------------------------------
# Graph 3 — rival write node
# ---------------------------------------------------------------------------


def make_write_rival_node(
    session: Session,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_write_rival(state: dict[str, Any]) -> dict[str, Any]:
        dominant = state["dominant_creature"]
        concept = state["concept"]
        taunts = state["taunts"]
        counter_design = state["counter_design"]

        # Rival uses same tier as dominant creature
        tier = dominant.get("tier", "common")
        from backend.graphs.nodes.validators import TIER_BUDGETS

        budget, max_single, ability_slots = TIER_BUDGETS[tier]

        # Build rival stats: boost the dominant's weak stat, keep others balanced
        boost_stat = counter_design.get("boost_stat", "speed")
        stat_names = ["health", "attack", "defense", "speed"]
        remaining = budget
        stats: dict[str, int] = {}
        for idx, stat_name in enumerate(stat_names):
            remaining_slots = len(stat_names) - idx - 1
            min_val = max(1, remaining - (remaining_slots * max_single))
            # Bias toward boost_stat
            if stat_name == boost_stat:
                max_val = min(max_single, remaining - remaining_slots)
                value = min(max_single, max_val)
            else:
                max_val = min(max_single, remaining - remaining_slots)
                value = max(min_val, min(max_val, remaining // max(1, remaining_slots + 1)))
            stats[stat_name] = max(min_val, min(max_val, value))
            remaining -= stats[stat_name]

        # Ensure budget is exactly met by adjusting boost_stat
        diff = budget - sum(stats.values())
        stats[boost_stat] = max(1, min(max_single, stats.get(boost_stat, 1) + diff))

        rival_id = shortuuid.uuid()
        rival = Creature(
            id=rival_id,
            name=concept["name"],
            tier=tier,
            element=counter_design["counter_element"],
            rival_of=dominant["id"],
            stats=stats,
            visual_descriptor=concept.get("visual_descriptor", {}),
            behavior_weights=concept.get("behavior_weights", {}),
            lore=concept["lore"],
            personality=concept["personality"],
            fighting_style=concept["fighting_style"],
        )
        session.add(rival)

        # Generate ability_slots abilities for the rival
        from random import Random

        rng = Random(f"{dominant['id']}:rival:abilities")
        ability_names = ["Rift Slash", "Ember Arc", "Stone Pulse", "Volt Pin", "Frost Lock"]
        for slot_idx in range(min(ability_slots, 2)):
            ability_name = rng.choice(ability_names)
            session.add(
                Ability(
                    id=shortuuid.uuid(),
                    creature_id=rival_id,
                    name=f"Counter {ability_name} {slot_idx + 1}",
                    type=counter_design["counter_element"],
                    energy_cost=10 + slot_idx * 5,
                    cooldown=1 + slot_idx,
                    effect=rng.choice(["damage", "stun", "slow", "shield_break"]),
                    description=(
                        f"Precision strike tuned to exploit {dominant['name']}'s weaknesses."
                    ),
                )
            )

        for trigger, lines in taunts.items():
            for line in lines:
                session.add(
                    Taunt(
                        id=shortuuid.uuid(),
                        creature_id=rival_id,
                        trigger=trigger,
                        text=line,
                    )
                )

        session.commit()
        logger.bind(
            stage="write_rival",
            rival_id=rival_id,
            dominant_id=dominant["id"],
        ).info("rival | rival persisted")
        return {"creature_id": rival_id}

    return node_write_rival


# ---------------------------------------------------------------------------
# Graph 4 — commentary write + broadcast nodes
# ---------------------------------------------------------------------------


def make_write_commentary_node(
    session: Session,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_write_commentary(state: dict[str, Any]) -> dict[str, Any]:
        lines = state.get("commentary_lines") or []
        trigger = state.get("trigger_event") or "periodic"
        threads = state.get("narrative_threads") or []
        snapshot = state.get("simulation_snapshot") or {}

        from sqlmodel import func

        count_result = session.exec(
            select(func.count()).select_from(Commentary)
        ).one()
        sequence_index = count_result if count_result is not None else 0

        commentary_ids: list[str] = []
        for line in lines:
            commentary_id = shortuuid.uuid()
            session.add(
                Commentary(
                    id=commentary_id,
                    text=line,
                    trigger=trigger,
                    threads={
                        "threads": threads,
                        "element_counts": snapshot.get("element_counts", {}),
                    },
                    sequence_index=sequence_index,
                )
            )
            commentary_ids.append(commentary_id)
            sequence_index += 1

        session.commit()
        logger.bind(stage="write_commentary", count=len(lines), trigger=trigger).info(
            "commentary | persisted"
        )
        return {}

    return node_write_commentary


def make_broadcast_commentary_node(
    manager: Any,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node_broadcast_commentary(state: dict[str, Any]) -> dict[str, Any]:
        lines = state.get("commentary_lines") or []
        trigger = state.get("trigger_event") or "periodic"
        threads = state.get("narrative_threads") or []

        event = {
            "type": "commentary",
            "trigger": trigger,
            "lines": lines,
            "threads": threads,
        }
        manager.broadcast_sync(event)
        logger.bind(stage="broadcast_commentary", lines=len(lines)).info(
            "commentary | broadcast"
        )
        return {}

    return node_broadcast_commentary
