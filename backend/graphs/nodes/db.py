from __future__ import annotations

from typing import Any

import shortuuid
from sqlmodel import Session

from backend.db.models import Ability, Creature, Taunt


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
