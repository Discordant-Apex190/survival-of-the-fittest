"""WebSocket endpoint — /ws

Clients connect here to receive real-time events from the simulation:
- fight_result: a fight completed
- commentary: Chronicler lines
- evolution: creature evolved
- rival_spawned: rival creature created
- extinction: creature went extinct
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.ws.manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; server pushes events via manager.broadcast()
            data = await websocket.receive_text()
            # Echo ping/pong for keep-alive support
            if data.strip() == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.bind(stage="ws_disconnect").info("websocket | client disconnected cleanly")
    except Exception as exc:
        manager.disconnect(websocket)
        logger.bind(stage="ws_error", error=str(exc)).warning("websocket | connection error")
