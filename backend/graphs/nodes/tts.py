from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from sqlmodel import Session, select

from backend.core.config import get_settings
from backend.db.models import Taunt
from backend.db.session import engine


def _tts_bytes(text: str) -> bytes:
    settings = get_settings()
    url = "https://api.cartesia.ai/tts/bytes"
    payload = {
        "model_id": settings.cartesia_tts_model,
        "transcript": text,
        "voice": {"mode": "id", "id": settings.cartesia_voice_id},
        "output_format": {
            "container": "wav",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
        },
        "language": settings.cartesia_language,
    }
    headers = {
        "X-API-Key": settings.cartesia_api_key,
        "Cartesia-Version": settings.cartesia_api_version,
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=45.0) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content


def _pick_taunt_line(state: dict[str, Any]) -> tuple[str, str] | None:
    taunts: dict[str, list[str]] = state.get("taunts") or {}
    for trigger in ("intro", "win", "ability", "loss", "ko"):
        lines = taunts.get(trigger) or []
        if lines:
            return trigger, lines[0]
    return None


def _persist_audio_path(creature_id: str, trigger: str, audio_path: Path) -> None:
    with Session(engine) as session:
        taunt = session.exec(
            select(Taunt)
            .where(Taunt.creature_id == creature_id)
            .where(Taunt.trigger == trigger)
            .order_by(Taunt.id)
        ).first()
        if taunt is None:
            return
        taunt.audio_path = str(audio_path)
        session.add(taunt)
        session.commit()


def node_queue_tts(state: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    creature_id = state.get("creature_id")
    if settings.app_env == "test" or not settings.cartesia_api_key or not creature_id:
        logger.bind(stage="queue_tts_skip", creature_id=creature_id).debug(
            "creature_factory | TTS skipped"
        )
        return {}

    picked = _pick_taunt_line(state)
    if picked is None:
        logger.bind(stage="queue_tts_skip", creature_id=creature_id).debug(
            "creature_factory | no taunt line found for TTS"
        )
        return {}

    trigger, line = picked
    try:
        audio = _tts_bytes(line)
        out_dir = Path(settings.audio_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{creature_id}_{trigger}.wav"
        output_path.write_bytes(audio)
        _persist_audio_path(creature_id, trigger, output_path)
        logger.bind(
            stage="queue_tts_done",
            creature_id=creature_id,
            trigger=trigger,
            path=str(output_path),
        ).info("creature_factory | TTS generated")
    except Exception as exc:  # noqa: BLE001
        logger.bind(stage="queue_tts_error", creature_id=creature_id, error=str(exc)).warning(
            "creature_factory | TTS generation failed"
        )
    return {}
