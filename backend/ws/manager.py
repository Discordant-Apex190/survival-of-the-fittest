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
        # Capture the running event loop the first time a client connects.
        # This is always called from an async context, so get_running_loop() is safe.
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
        """Broadcast from a sync context (threadpool thread or BackgroundTask).

        Uses run_coroutine_threadsafe to schedule the coroutine on the main
        event loop that owns all WebSocket connections.  If no client has ever
        connected the loop reference is None and the call is a safe no-op.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            # No clients have connected yet — nothing to broadcast to.
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# App-wide singleton
manager = ConnectionManager()
