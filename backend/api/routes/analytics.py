"""Analytics routes — DuckDB querying SQLite directly.

All endpoints are read-only and return pre-aggregated data for the 5 analytics tabs.
"""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.core.config import get_settings

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_path() -> str:
    """Strip sqlite:/// prefix from DATABASE_URL to get the raw file path."""
    url = get_settings().database_url
    return url.removeprefix("sqlite:///")


def _duckdb_con() -> duckdb.DuckDBPyConnection:
    """Open a fresh in-memory DuckDB connection with the SQLite scanner loaded."""
    con = duckdb.connect()
    con.execute("LOAD sqlite")
    return con


def _scan(table: str) -> str:
    """Return a sqlite_scan() expression for a given table."""
    return f"sqlite_scan('{_db_path()}', '{table}')"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ElementMatrixRow(BaseModel):
    winner_element: str
    loser_element: str
    wins: int


class AbilityStatRow(BaseModel):
    name: str
    type: str
    creature_count: int
    avg_energy_cost: float


class ExtinctCreature(BaseModel):
    id: str
    name: str
    tier: str
    element: str
    generation: int
    wins: int
    losses: int
    extinction_cause: str | None
    created_at: str


class PopulationDay(BaseModel):
    date: str
    total: int
    active: int
    retired: int
    extinct: int


class SimStats(BaseModel):
    total_creatures: int
    active_creatures: int
    total_fights: int
    avg_fight_duration: float
    total_evolutions: int
    total_rivals: int
    total_extinct: int
    most_common_element: str | None
    most_common_tier: str | None


# ---------------------------------------------------------------------------
# GET /analytics/element-matrix
# ---------------------------------------------------------------------------


@router.get("/element-matrix", response_model=list[ElementMatrixRow])
def element_matrix() -> list[ElementMatrixRow]:
    """Win counts by (winner_element, loser_element) pair."""
    try:
        con = _duckdb_con()
        rows = con.execute(
            f"""
            SELECT
                w.element AS winner_element,
                l.element AS loser_element,
                COUNT(*) AS wins
            FROM {_scan('fights')} f
            JOIN {_scan('creatures')} w ON f.winner_id = w.id
            JOIN {_scan('creatures')} l
                ON (f.creature_a_id = l.id OR f.creature_b_id = l.id)
                AND l.id != f.winner_id
            WHERE f.winner_id IS NOT NULL
            GROUP BY w.element, l.element
            ORDER BY w.element, l.element
            """
        ).fetchall()
        return [
            ElementMatrixRow(winner_element=r[0], loser_element=r[1], wins=r[2]) for r in rows
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DuckDB query failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /analytics/ability-stats
# ---------------------------------------------------------------------------


@router.get("/ability-stats", response_model=list[AbilityStatRow])
def ability_stats() -> list[AbilityStatRow]:
    """Ability usage grouped by name+type, sorted by creature_count desc."""
    try:
        con = _duckdb_con()
        rows = con.execute(
            f"""
            SELECT
                a.name,
                a.type,
                COUNT(*) AS creature_count,
                AVG(a.energy_cost) AS avg_energy_cost
            FROM {_scan('abilities')} a
            GROUP BY a.name, a.type
            ORDER BY creature_count DESC
            LIMIT 50
            """
        ).fetchall()
        return [
            AbilityStatRow(
                name=r[0], type=r[1], creature_count=r[2], avg_energy_cost=round(r[3], 1)
            )
            for r in rows
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DuckDB query failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /analytics/extinction-log
# ---------------------------------------------------------------------------


@router.get("/extinction-log", response_model=list[ExtinctCreature])
def extinction_log() -> list[ExtinctCreature]:
    """All extinct creatures, most recent first."""
    try:
        con = _duckdb_con()
        rows = con.execute(
            f"""
            SELECT id, name, tier, element, generation, wins, losses,
                   extinction_cause, CAST(created_at AS VARCHAR) AS created_at
            FROM {_scan('creatures')}
            WHERE status = 'extinct'
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [
            ExtinctCreature(
                id=r[0],
                name=r[1],
                tier=r[2],
                element=r[3],
                generation=r[4],
                wins=r[5],
                losses=r[6],
                extinction_cause=r[7],
                created_at=str(r[8]),
            )
            for r in rows
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DuckDB query failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /analytics/population
# ---------------------------------------------------------------------------


@router.get("/population", response_model=list[PopulationDay])
def population() -> list[PopulationDay]:
    """Creatures created per calendar day, broken down by final status."""
    try:
        con = _duckdb_con()
        rows = con.execute(
            f"""
            SELECT
                CAST(created_at AS DATE) AS day,
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'active'  THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status = 'retired' THEN 1 ELSE 0 END) AS retired,
                SUM(CASE WHEN status = 'extinct' THEN 1 ELSE 0 END) AS extinct
            FROM {_scan('creatures')}
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()
        return [
            PopulationDay(
                date=str(r[0]),
                total=r[1],
                active=r[2],
                retired=r[3],
                extinct=r[4],
            )
            for r in rows
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DuckDB query failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /analytics/sim-stats
# ---------------------------------------------------------------------------


@router.get("/sim-stats", response_model=SimStats)
def sim_stats() -> SimStats:
    """Single-row aggregate over the entire simulation."""
    try:
        con = _duckdb_con()

        def scalar(sql: str) -> Any:
            return con.execute(sql).fetchone()[0]  # type: ignore[index]

        total_creatures = scalar(f"SELECT COUNT(*) FROM {_scan('creatures')}")
        active_creatures = scalar(
            f"SELECT COUNT(*) FROM {_scan('creatures')} WHERE status = 'active'"
        )
        total_fights = scalar(f"SELECT COUNT(*) FROM {_scan('fights')}")
        avg_dur_raw = scalar(f"SELECT AVG(duration_turns) FROM {_scan('fights')}")
        avg_fight_duration = round(float(avg_dur_raw or 0), 1)
        total_evolutions = scalar(f"SELECT COUNT(*) FROM {_scan('evolutions')}")
        total_rivals = scalar(
            f"SELECT COUNT(*) FROM {_scan('creatures')} WHERE rival_of IS NOT NULL"
        )
        total_extinct = scalar(
            f"SELECT COUNT(*) FROM {_scan('creatures')} WHERE status = 'extinct'"
        )
        elem_row = con.execute(
            f"""
            SELECT element FROM {_scan('creatures')}
            GROUP BY element ORDER BY COUNT(*) DESC LIMIT 1
            """
        ).fetchone()
        tier_row = con.execute(
            f"""
            SELECT tier FROM {_scan('creatures')}
            GROUP BY tier ORDER BY COUNT(*) DESC LIMIT 1
            """
        ).fetchone()

        return SimStats(
            total_creatures=total_creatures,
            active_creatures=active_creatures,
            total_fights=total_fights,
            avg_fight_duration=avg_fight_duration,
            total_evolutions=total_evolutions,
            total_rivals=total_rivals,
            total_extinct=total_extinct,
            most_common_element=elem_row[0] if elem_row else None,
            most_common_tier=tier_row[0] if tier_row else None,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DuckDB query failed: {exc}",
        ) from exc
