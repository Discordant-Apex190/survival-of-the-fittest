from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from backend.db.session import get_session
from backend.graphs.creature_factory import run_creature_factory_graph
from backend.graphs.nodes.validators import SeedParams

router = APIRouter(prefix="/creatures", tags=["creatures"])


class GenerateCreatureRequest(BaseModel):
    seed_params: SeedParams


class GenerateCreatureResponse(BaseModel):
    creature_id: str
    name: str
    tier: str
    element: str
    ability_count: int
    taunt_count: int
    retry_count: int
    graph_state: dict


@router.post(
    "/generate", response_model=GenerateCreatureResponse, status_code=status.HTTP_201_CREATED
)
def generate_creature(
    payload: GenerateCreatureRequest,
    session: Annotated[Session, Depends(get_session)],
) -> GenerateCreatureResponse:
    try:
        result = run_creature_factory_graph(session, seed_params=payload.seed_params.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return GenerateCreatureResponse(
        creature_id=result.creature_id,
        name=result.name,
        tier=result.tier,
        element=result.element,
        ability_count=result.ability_count,
        taunt_count=result.taunt_count,
        retry_count=result.retry_count,
        graph_state=result.graph_state,
    )
