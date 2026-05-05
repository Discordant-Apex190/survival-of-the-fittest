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

    async def connect(self, websocket: WebSocket) -> None:
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
        """Fire-and-forget broadcast from sync context (e.g. LangGraph node).

        Creates a new event loop task if a running loop exists, otherwise
        schedules via asyncio.run. Safe to call from BackgroundTask context.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event))
        except RuntimeError:
            asyncio.run(self.broadcast(event))

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# App-wide singleton
manager = ConnectionManager()
