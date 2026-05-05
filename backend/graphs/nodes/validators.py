from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

TIER_BUDGETS: dict[str, tuple[int, int, int]] = {
    "common": (80, 25, 1),
    "uncommon": (100, 30, 2),
    "rare": (125, 38, 3),
    "legendary": (160, 50, 4),
}


class SeedParams(BaseModel):
    element: Literal["fire", "void", "nature", "ice", "electric"]
    archetype: str = Field(min_length=2, max_length=40)
    tier: Literal["common", "uncommon", "rare", "legendary"]
    biome: str = Field(min_length=2, max_length=60)
    stat_budget: int = Field(gt=0)

    @field_validator("stat_budget")
    @classmethod
    def validate_budget_matches_tier(cls, value: int, info) -> int:
        tier = info.data.get("tier")
        if tier and value != TIER_BUDGETS[tier][0]:
            expected = TIER_BUDGETS[tier][0]
            raise ValueError(f"stat_budget must be {expected} for tier '{tier}'")
        return value


class ConceptPayload(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    lore: str = Field(min_length=10, max_length=1000)
    personality: str = Field(min_length=3, max_length=120)
    fighting_style: str = Field(min_length=3, max_length=120)
    visual_descriptor: dict[str, Any]
    behavior_weights: dict[str, float]


class AbilityPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: str = Field(min_length=2, max_length=40)
    energy_cost: int = Field(gt=0, le=100)
    cooldown: int = Field(ge=0, le=20)
    effect: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=5, max_length=500)


class StatsPayload(BaseModel):
    health: int = Field(gt=0)
    attack: int = Field(gt=0)
    defense: int = Field(gt=0)
    speed: int = Field(gt=0)


def validate_generation_payload(
    *,
    seed_params: dict[str, Any],
    concept: dict[str, Any],
    stats: dict[str, Any],
    abilities: list[dict[str, Any]],
    taunts: dict[str, list[str]],
) -> list[str]:
    errors: list[str] = []

    try:
        seed = SeedParams.model_validate(seed_params)
    except ValidationError as exc:
        return [f"seed_params: {err['msg']}" for err in exc.errors()]

    try:
        ConceptPayload.model_validate(concept)
    except ValidationError as exc:
        errors.extend([f"concept: {err['msg']}" for err in exc.errors()])

    try:
        parsed_stats = StatsPayload.model_validate(stats)
    except ValidationError as exc:
        errors.extend([f"stats: {err['msg']}" for err in exc.errors()])
        parsed_stats = None

    parsed_abilities: list[AbilityPayload] = []
    for ability in abilities:
        try:
            parsed_abilities.append(AbilityPayload.model_validate(ability))
        except ValidationError as exc:
            errors.extend([f"ability: {err['msg']}" for err in exc.errors()])

    budget, max_single_stat, max_ability_slots = TIER_BUDGETS[seed.tier]
    if parsed_stats:
        total = (
            parsed_stats.health + parsed_stats.attack + parsed_stats.defense + parsed_stats.speed
        )
        if total != budget:
            errors.append(f"stats: total stat budget must equal {budget}, got {total}")

        for stat_name, value in parsed_stats.model_dump().items():
            if value > max_single_stat:
                errors.append(
                    "stats: "
                    f"{stat_name} exceeds max single stat {max_single_stat} "
                    f"for tier {seed.tier}"
                )

    if len(parsed_abilities) > max_ability_slots:
        errors.append(
            "abilities: "
            f"max slots for tier {seed.tier} is {max_ability_slots}, "
            f"got {len(parsed_abilities)}"
        )

    if not taunts:
        errors.append("taunts: at least one trigger set is required")
    for trigger, lines in taunts.items():
        if not lines:
            errors.append(f"taunts: trigger '{trigger}' must contain at least one line")
        for line in lines:
            if not line.strip():
                errors.append(f"taunts: trigger '{trigger}' contains an empty line")

    return errors
