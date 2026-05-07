"""WebSocket connection manager — singleton used across the app.

All connected clients receive broadcast messages as JSON.
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

    async def connect(self, websocket: WebSocket) -> None:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        await websocket.accept()
        self._connections.append(websocket)
        logger.bind(stage="ws_connect", total=len(self._connections)).info(
            "websocket | client connected"
        )

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not websocket]
        logger.bind(stage="ws_disconnect", total=len(self._connections)).info(
            "websocket | client disconnected"
        )

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

        Schedules the coroutine on the main event loop.  The loop is
        captured at startup so this works before any WS client connects.
        """
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# App-wide singleton
manager = ConnectionManager()
