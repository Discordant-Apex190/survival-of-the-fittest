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
            "container": "mp3",
            "encoding": "mp3",
            "sample_rate": 44100,
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


def _audio_path(creature_id: str, taunt_id: str, audio_dir: Path) -> Path:
    """Return the .mp3 path for a taunt, creating the parent directory."""
    creature_dir = audio_dir / "creatures" / creature_id
    creature_dir.mkdir(parents=True, exist_ok=True)
    return creature_dir / f"{taunt_id}.mp3"


def node_queue_tts(state: dict[str, Any]) -> dict[str, Any]:
    """Generate MP3 audio for every taunt belonging to the newly created creature.

    Skips silently in test environments or when the Cartesia API key is absent.
    Already-generated taunts (audio_path set) are skipped.
    """
    settings = get_settings()
    creature_id = state.get("creature_id")

    if settings.app_env == "test" or not settings.cartesia_api_key or not creature_id:
        logger.bind(stage="queue_tts_skip", creature_id=creature_id).debug(
            "creature_factory | TTS skipped"
        )
        return {}

    audio_dir = Path(settings.audio_dir)
    generated = 0
    failed = 0

    with Session(engine) as session:
        taunts = session.exec(
            select(Taunt).where(Taunt.creature_id == creature_id)
        ).all()

        for taunt in taunts:
            if taunt.audio_path:
                continue  # already cached — never re-call Cartesia
            try:
                audio = _tts_bytes(taunt.text)
                path = _audio_path(creature_id, taunt.id, audio_dir)
                path.write_bytes(audio)
                taunt.audio_path = str(path)
                session.add(taunt)
                generated += 1
            except Exception as exc:  # noqa: BLE001
                logger.bind(
                    stage="queue_tts_error",
                    creature_id=creature_id,
                    taunt_id=taunt.id,
                    error=str(exc),
                ).warning("creature_factory | TTS failed for taunt, skipping")
                failed += 1

        if generated:
            session.commit()

    logger.bind(
        stage="queue_tts_done",
        creature_id=creature_id,
        generated=generated,
        failed=failed,
    ).info("creature_factory | TTS batch complete")
    return {}
