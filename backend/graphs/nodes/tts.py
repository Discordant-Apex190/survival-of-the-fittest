from __future__ import annotations

from typing import Any

from loguru import logger


def node_queue_tts(state: dict[str, Any]) -> dict[str, Any]:
    """Stub TTS node — enqueues audio generation once Cartesia integration is added."""
    logger.bind(stage="queue_tts", creature_id=state.get("creature_id")).debug(
        "creature_factory | TTS queued (stub)"
    )
    return {}
