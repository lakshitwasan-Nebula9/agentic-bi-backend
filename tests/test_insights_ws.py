"""Integration test for the /insights/ws WebSocket route through the ASGI stack.

The Redis listener is stubbed out so the test needs no broker — it verifies the
route accepts a client, registers it with the shared ConnectionManager, and that
a broadcast reaches the connected client.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    async def _noop_listener():
        await asyncio.Event().wait()  # idle until cancelled on shutdown

    monkeypatch.setattr("app.main.run_insight_listener", _noop_listener)
    import app.main

    with TestClient(app.main.app) as test_client:
        yield test_client


def test_ws_connect_registers_and_unregisters(client):
    from app.ws.connection_manager import connection_manager

    before = connection_manager.active_count
    with client.websocket_connect("/api/v1/insights/ws"):
        assert connection_manager.active_count == before + 1
    assert connection_manager.active_count == before


def test_ws_receives_broadcast(client):
    from app.ws.connection_manager import connection_manager

    with client.websocket_connect("/api/v1/insights/ws") as ws:
        # Broadcast from within the app's event loop via its portal, so the
        # send happens on the same loop the WebSocket lives on.
        message = {"type": "insight_detected", "data": {"id": "abc", "insight_type": "spike"}}
        client.portal.call(connection_manager.broadcast, message)
        assert ws.receive_json() == message
