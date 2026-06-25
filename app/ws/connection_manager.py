"""In-memory pool of active frontend WebSocket connections.

A single process-wide ``connection_manager`` instance is shared by the WebSocket
route (which registers/unregisters clients) and the Redis listener (which
broadcasts insight events to every client). Under multiple Uvicorn workers each
worker keeps its own pool and runs its own listener, so a stream message fans out
to every worker's clients independently.
"""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept the handshake and register the client."""
        await websocket.accept()
        async with self._lock:
            self._active.add(websocket)
        logger.info("WebSocket client connected (active=%d)", len(self._active))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._active.discard(websocket)
        logger.info("WebSocket client disconnected (active=%d)", len(self._active))

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to every connected client, dropping dead ones."""
        async with self._lock:
            targets = list(self._active)

        dead: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 — a broken client must not stop the broadcast
                dead.append(websocket)

        if dead:
            async with self._lock:
                for websocket in dead:
                    self._active.discard(websocket)
            logger.info("Pruned %d dead WebSocket connection(s)", len(dead))

    @property
    def active_count(self) -> int:
        return len(self._active)


# Process-wide singleton shared by the route and the listener.
connection_manager = ConnectionManager()
