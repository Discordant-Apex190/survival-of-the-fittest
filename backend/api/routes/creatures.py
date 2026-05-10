from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.db.models import Ability, Creature, Fight, Taunt
from backend.db.session import get_session
from backend.graphs.creature_factory import run_creature_factory_graph
from backend.graphs.evolution import EVOLUTION_WIN_THRESHOLD, run_evolution_graph
from backend.graphs.nodes.stat_generator import ABILITY_MATRIX
from backend.graphs.nodes.validators import AbilityPayload, SeedParams
from backend.graphs.rival import RIVAL_DOMINANCE_THRESHOLD, run_rival_graph

router = APIRouter(prefix="/creatures", tags=["creatures"])

# ---------------------------------------------------------------------------
# Shared response schemas
# ---------------------------------------------------------------------------

ElementFilter = Literal["fire", "void", "nature", "ice", "electric"]
TierFilter = Literal["common", "uncommon", "rare", "legendary"]
StatusFilter = Literal["active", "retired", "extinct"]


class AbilityOut(BaseModel):
    id: str
    name: str
    type: str
    energy_cost: int
    cooldown: int
    effect: str
    description: str


class TauntOut(BaseModel):
    id: str
    trigger: str
    text: str
    audio_path: str | None


class CreatureSummary(BaseModel):
    id: str
    name: str
    tier: str
    element: str
    generation: int
    wins: int
    losses: int
    status: str
    stats: dict[str, Any]
    fighting_style: str


class CreatureDetail(CreatureSummary):
    lore: str
    personality: str
    visual_descriptor: dict[str, Any]
    behavior_weights: dict[str, Any]
    abilities: list[AbilityOut]
    taunts: list[TauntOut]


class GenerateCreatureRequest(BaseModel):
    seed_params: SeedParams
    preferred_name: str | None = Field(default=None, max_length=30)
    selected_abilities: list[AbilityPayload] = Field(default_factory=list)


class GenerateCreatureResponse(BaseModel):
    creature_id: str
    name: str
    tier: str
    element: str
    ability_count: int
    taunt_count: int
    retry_count: int
    graph_state: dict


class LineageNode(BaseModel):
    id: str
    name: str
    tier: str
    element: str
    generation: int
    wins: int
    losses: int
    status: str
    parent_id: str | None
    rival_of: str | None


class AbilityTemplateOut(BaseModel):
    name: str
    type: str
    energy_cost: int
    cooldown: int
    effect: str
    description: str


# ---------------------------------------------------------------------------
# POST /creatures/generate
# ---------------------------------------------------------------------------


@router.post(
    "/generate", response_model=GenerateCreatureResponse, status_code=status.HTTP_201_CREATED
)
def generate_creature(
    payload: GenerateCreatureRequest,
    session: Annotated[Session, Depends(get_session)],
) -> GenerateCreatureResponse:
    seed_params = payload.seed_params.model_dump()
    if payload.selected_abilities:
        seed_params["selected_abilities"] = [a.model_dump() for a in payload.selected_abilities]

    try:
        result = run_creature_factory_graph(session, seed_params=seed_params)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    preferred_name = (payload.preferred_name or "").strip()
    response_name = result.name
    if preferred_name:
        creature = session.get(Creature, result.creature_id)
        if creature is not None:
            creature.name = preferred_name
            session.add(creature)
            session.commit()
            response_name = preferred_name

    return GenerateCreatureResponse(
        creature_id=result.creature_id,
        name=response_name,
        tier=result.tier,
        element=result.element,
        ability_count=result.ability_count,
        taunt_count=result.taunt_count,
        retry_count=result.retry_count,
        graph_state=result.graph_state,
    )


# ---------------------------------------------------------------------------
# GET /creatures
# ---------------------------------------------------------------------------


@router.get("", response_model=list[CreatureSummary])
def list_creatures(
    session: Annotated[Session, Depends(get_session)],
    element: Annotated[ElementFilter | None, Query()] = None,
    tier: Annotated[TierFilter | None, Query()] = None,
    status: Annotated[StatusFilter | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[CreatureSummary]:
    query = select(Creature)
    if element:
        query = query.where(Creature.element == element)
    if tier:
        query = query.where(Creature.tier == tier)
    if status:
        query = query.where(Creature.status == status)
    query = query.offset(offset).limit(limit)

    rows = session.exec(query).all()
    return [
        CreatureSummary(
            id=c.id,
            name=c.name,
            tier=c.tier,
            element=c.element,
            generation=c.generation,
            wins=c.wins,
            losses=c.losses,
            status=c.status,
            stats=c.stats,
            fighting_style=c.fighting_style,
        )
        for c in rows
    ]


# ---------------------------------------------------------------------------
# GET /creatures/lineage  — must be before /{creature_id}
# ---------------------------------------------------------------------------


@router.get("/lineage", response_model=list[LineageNode])
def get_lineage(
    session: Annotated[Session, Depends(get_session)],
) -> list[LineageNode]:
    """Return all creatures with parent/rival edges for tree rendering."""
    rows = session.exec(select(Creature)).all()
    return [
        LineageNode(
            id=c.id,
            name=c.name,
            tier=c.tier,
            element=c.element,
            generation=c.generation,
            wins=c.wins,
            losses=c.losses,
            status=c.status,
            parent_id=c.parent_id,
            rival_of=c.rival_of,
        )
        for c in rows
    ]


# ---------------------------------------------------------------------------
# GET /creatures/ability-options  — must be before /{creature_id}
# ---------------------------------------------------------------------------


@router.get("/ability-options", response_model=dict[str, list[AbilityTemplateOut]])
def get_ability_options() -> dict[str, list[AbilityTemplateOut]]:
    return {
        element: [AbilityTemplateOut(**ability) for ability in options]
        for element, options in ABILITY_MATRIX.items()
    }


# ---------------------------------------------------------------------------
# GET /creatures/{creature_id}
# ---------------------------------------------------------------------------


@router.get("/{creature_id}", response_model=CreatureDetail)
def get_creature(
    creature_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> CreatureDetail:
    creature = session.get(Creature, creature_id)
    if not creature:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creature not found")

    abilities = session.exec(
        select(Ability).where(Ability.creature_id == creature_id)
    ).all()
    taunts = session.exec(
        select(Taunt).where(Taunt.creature_id == creature_id)
    ).all()

    return CreatureDetail(
        id=creature.id,
        name=creature.name,
        tier=creature.tier,
        element=creature.element,
        generation=creature.generation,
        wins=creature.wins,
        losses=creature.losses,
        status=creature.status,
        stats=creature.stats,
        fighting_style=creature.fighting_style,
        lore=creature.lore,
        personality=creature.personality,
        visual_descriptor=creature.visual_descriptor,
        behavior_weights=creature.behavior_weights,
        abilities=[
            AbilityOut(
                id=a.id,
                name=a.name,
                type=a.type,
                energy_cost=a.energy_cost,
                cooldown=a.cooldown,
                effect=a.effect,
                description=a.description,
            )
            for a in abilities
        ],
        taunts=[
            TauntOut(id=t.id, trigger=t.trigger, text=t.text, audio_path=t.audio_path)
            for t in taunts
        ],
    )


# ---------------------------------------------------------------------------
# POST /creatures/{creature_id}/evolve
# ---------------------------------------------------------------------------


class EvolveCreatureResponse(BaseModel):
    child_id: str
    parent_id: str
    name: str
    tier: str
    generation: int
    stat_boosts: dict[str, int]
    new_ability: bool
    retry_count: int
    graph_state: dict


@router.post("/{creature_id}/evolve", response_model=EvolveCreatureResponse)
def evolve_creature(
    creature_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> EvolveCreatureResponse:
    creature = session.get(Creature, creature_id)
    if not creature:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creature not found")

    if creature.wins < EVOLUTION_WIN_THRESHOLD:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Creature needs {EVOLUTION_WIN_THRESHOLD} wins to evolve "
                f"(currently {creature.wins})"
            ),
        )
    if creature.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Creature is '{creature.status}' and cannot evolve",
        )

    fights = session.exec(
        select(Fight).where(
            (Fight.creature_a_id == creature_id) | (Fight.creature_b_id == creature_id)
        )
    ).all()

    fight_history = [
        {
            "fight_id": f.id,
            "won": f.winner_id == creature_id,
            "opponent_element": None,
            "abilities_used": [],
            "turns": f.duration_turns,
        }
        for f in fights
    ]

    parent_creature = {
        "id": creature.id,
        "name": creature.name,
        "tier": creature.tier,
        "element": creature.element,
        "generation": creature.generation,
        "stats": creature.stats,
        "lore": creature.lore,
        "personality": creature.personality,
        "fighting_style": creature.fighting_style,
        "visual_descriptor": creature.visual_descriptor,
        "behavior_weights": creature.behavior_weights,
    }

    try:
        result = run_evolution_graph(
            session,
            parent_creature=parent_creature,
            fight_history=fight_history,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return EvolveCreatureResponse(
        child_id=result.creature_id,
        parent_id=result.parent_id,
        name=result.name,
        tier=result.tier,
        generation=result.generation,
        stat_boosts=result.stat_boosts,
        new_ability=result.new_ability,
        retry_count=result.retry_count,
        graph_state=result.graph_state,
    )


# ---------------------------------------------------------------------------
# POST /creatures/{creature_id}/spawn-rival
# ---------------------------------------------------------------------------


class SpawnRivalResponse(BaseModel):
    rival_id: str
    dominant_id: str
    rival_name: str
    counter_element: str
    counter_archetype: str
    retry_count: int


@router.post(
    "/{creature_id}/spawn-rival",
    response_model=SpawnRivalResponse,
    status_code=status.HTTP_201_CREATED,
)
def spawn_rival(
    creature_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> SpawnRivalResponse:
    creature = session.get(Creature, creature_id)
    if not creature:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creature not found")

    if creature.wins < RIVAL_DOMINANCE_THRESHOLD:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Creature needs {RIVAL_DOMINANCE_THRESHOLD} wins to spawn a rival "
                f"(currently {creature.wins})"
            ),
        )

    dominant_creature = {
        "id": creature.id,
        "name": creature.name,
        "tier": creature.tier,
        "element": creature.element,
        "generation": creature.generation,
        "wins": creature.wins,
        "stats": creature.stats,
        "lore": creature.lore,
        "personality": creature.personality,
        "fighting_style": creature.fighting_style,
        "visual_descriptor": creature.visual_descriptor,
        "behavior_weights": creature.behavior_weights,
    }

    try:
        result = run_rival_graph(session, dominant_creature=dominant_creature)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return SpawnRivalResponse(
        rival_id=result.rival_id,
        dominant_id=result.dominant_id,
        rival_name=result.rival_name,
        counter_element=result.counter_element,
        counter_archetype=result.counter_archetype,
        retry_count=result.retry_count,
    )
