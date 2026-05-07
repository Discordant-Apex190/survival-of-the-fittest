"""WebSocket connection manager — singleton used across the app.

Tracks connected clients and drives the betting-window mechanic:
  - start_betting_window(fight_id): open window, reset bet counter
  - record_bet(fight_id): one client has submitted; check threshold
  - wait_for_bets(fight_id, max_wait): blocks until threshold met or timeout
"""

from __future__ import annotations

import asyncio
import math
import threading
from typing import Any

import orjson
from fastapi import WebSocket
from loguru import logger

BET_THRESHOLD = 0.5   # fraction of connected clients that must bet


class ConnectionManager:
    """Manages active WebSocket connections and the betting-window countdown."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

        # Betting-window state
        self._bet_events: dict[str, threading.Event] = {}
        self._bet_counts: dict[str, int] = {}

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
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)

    # ------------------------------------------------------------------
    # Betting-window mechanic
    # ------------------------------------------------------------------

    def start_betting_window(self, fight_id: str) -> None:
        """Open a betting window for this fight. Called before fight_preview broadcast."""
        event = threading.Event()
        self._bet_events[fight_id] = event
        self._bet_counts[fight_id] = 0
        # If nobody is connected, resolve immediately
        if self.connection_count == 0:
            event.set()

    def record_bet(self, fight_id: str) -> None:
        """Signal that one client has placed a bet. May trigger the window to close."""
        if fight_id not in self._bet_counts:
            return
        self._bet_counts[fight_id] += 1
        self._maybe_close_window(fight_id)

    def _maybe_close_window(self, fight_id: str) -> None:
        event = self._bet_events.get(fight_id)
        if not event or event.is_set():
            return
        n_clients = self.connection_count
        n_bets    = self._bet_counts.get(fight_id, 0)
        needed    = max(1, math.ceil(BET_THRESHOLD * n_clients))
        if n_clients == 0 or n_bets >= needed:
            logger.bind(
                stage="betting_window",
                fight_id=fight_id[:8],
                n_bets=n_bets,
                n_clients=n_clients,
            ).info("betting | threshold met, starting fight")
            event.set()

    def wait_for_bets(self, fight_id: str, max_wait: float = 12.0) -> None:
        """Block (in a thread-pool thread) until threshold met or max_wait elapses."""
        event = self._bet_events.get(fight_id)
        if event:
            event.wait(timeout=max_wait)
        self._bet_events.pop(fight_id, None)
        self._bet_counts.pop(fight_id, None)

    def bet_progress(self, fight_id: str) -> tuple[int, int]:
        """Return (bets_received, needed) for UI feedback."""
        n_clients = self.connection_count
        n_bets    = self._bet_counts.get(fight_id, 0)
        needed    = max(1, math.ceil(BET_THRESHOLD * n_clients)) if n_clients > 0 else 0
        return n_bets, needed

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# App-wide singleton
manager = ConnectionManager()
