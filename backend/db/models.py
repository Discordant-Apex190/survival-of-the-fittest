from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.sqlite import JSON
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Creature(SQLModel, table=True):
    __tablename__ = "creatures"

    id: str = Field(primary_key=True, max_length=32)
    name: str = Field(index=True)
    tier: str = Field(index=True)
    element: str = Field(index=True)
    generation: int = Field(default=1)
    parent_id: str | None = Field(default=None, foreign_key="creatures.id")
    rival_of: str | None = Field(default=None, foreign_key="creatures.id")

    wins: int = Field(default=0)
    losses: int = Field(default=0)
    status: str = Field(default="active", index=True)

    stats: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    visual_descriptor: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    behavior_weights: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    lore: str = Field(default="")
    personality: str = Field(default="")
    fighting_style: str = Field(default="")
    extinction_cause: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Ability(SQLModel, table=True):
    __tablename__ = "abilities"

    id: str = Field(primary_key=True, max_length=32)
    creature_id: str = Field(foreign_key="creatures.id", index=True)

    name: str = Field(index=True)
    type: str
    energy_cost: int
    cooldown: int
    effect: str
    description: str


class Taunt(SQLModel, table=True):
    __tablename__ = "taunts"

    id: str = Field(primary_key=True, max_length=32)
    creature_id: str = Field(foreign_key="creatures.id", index=True)

    trigger: str = Field(index=True)
    text: str
    audio_path: str | None = Field(default=None)


class Fight(SQLModel, table=True):
    __tablename__ = "fights"

    id: str = Field(primary_key=True, max_length=32)
    creature_a_id: str = Field(foreign_key="creatures.id", index=True)
    creature_b_id: str = Field(foreign_key="creatures.id", index=True)
    winner_id: str | None = Field(default=None, foreign_key="creatures.id", index=True)

    tier: str = Field(index=True)
    duration_turns: int = Field(default=0)
    fight_log: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    recording_path: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class FightEvent(SQLModel, table=True):
    __tablename__ = "fight_events"

    id: str = Field(primary_key=True, max_length=32)
    fight_id: str = Field(foreign_key="fights.id", index=True)

    turn: int = Field(index=True)
    event_type: str = Field(index=True)
    actor_id: str | None = Field(default=None, foreign_key="creatures.id")
    target_id: str | None = Field(default=None, foreign_key="creatures.id")
    ability_name: str | None = Field(default=None)
    damage: int | None = Field(default=None)
    hp_remaining: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=utcnow, index=True)


class Evolution(SQLModel, table=True):
    __tablename__ = "evolutions"

    id: str = Field(primary_key=True, max_length=32)
    parent_id: str = Field(foreign_key="creatures.id", index=True)
    child_id: str = Field(foreign_key="creatures.id", index=True)

    trigger: str
    changes: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    evolution_reasoning: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Commentary(SQLModel, table=True):
    __tablename__ = "commentary"

    id: str = Field(primary_key=True, max_length=32)
    text: str
    trigger: str = Field(index=True)
    threads: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    sequence_index: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
