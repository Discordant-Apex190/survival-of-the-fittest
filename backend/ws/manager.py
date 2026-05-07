"""WebSocket connection manager — singleton used across the app.

All connected clients receive broadcast messages as JSON.
New clients receive a replay of the most recent fight immediately on connect.
"""

from __future__ import annotations

import asyncio
from typing import Any

import orjson
from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        # Replay buffer: the full sequence of events from the last fight
        self._replay: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket) -> None:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        await websocket.accept()
        self._connections.append(websocket)
        logger.bind(stage="ws_connect", total=len(self._connections)).info(
            "websocket | client connected"
        )
        # Replay the last fight to this client so they don't miss events
        # that fired before they connected.
        if self._replay:
            payload_list = [orjson.dumps(e).decode() for e in self._replay]
            for payload in payload_list:
                try:
                    await websocket.send_text(payload)
                except Exception:  # noqa: BLE001
                    break

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not websocket]
        logger.bind(stage="ws_disconnect", total=len(self._connections)).info(
            "websocket | client disconnected"
        )

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(self, event: dict[str, Any]) -> None:
        if not self._connections:
            return
        payload = orjson.dumps(event).decode()
        dead: list[WebSocket] = []
        for connection in list(self._connections):
            try:
                await connection.send_text(payload)
            except Exception:
                dead.append(connection)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_sync(self, event: dict[str, Any]) -> None:
        """Broadcast from a sync context (threadpool thread).

        Schedules the coroutine on the main event loop.  Safe no-op if
        the loop hasn't started yet — the event is still captured into
        the replay buffer via record_replay_event().
        """
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)

    # ------------------------------------------------------------------
    # Replay buffer management
    # ------------------------------------------------------------------

    def start_replay(self, fight_start_event: dict[str, Any]) -> None:
        """Begin a new replay buffer with the fight_start event."""
        self._replay = [fight_start_event]

    def record_replay_event(self, event: dict[str, Any]) -> None:
        """Append a fight_event to the current replay buffer."""
        self._replay.append(event)

    def finish_replay(self, fight_end_event: dict[str, Any]) -> None:
        """Seal the replay buffer with fight_end."""
        self._replay.append(fight_end_event)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# App-wide singleton
manager = ConnectionManager()
