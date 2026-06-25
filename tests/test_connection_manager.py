"""Unit tests for the WebSocket ConnectionManager.

Async methods are driven with asyncio.run() so they run under the plain pytest
runner (no pytest-asyncio configured in this repo). A FakeWebSocket stands in for
Starlette's WebSocket — no Redis or network needed.
"""

import asyncio

from app.ws.connection_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.accepted = False
        self.sent: list[dict] = []
        self.fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self.fail_on_send:
            raise RuntimeError("broken pipe")
        self.sent.append(message)


def test_connect_accepts_and_registers():
    mgr = ConnectionManager()
    ws = FakeWebSocket()

    asyncio.run(mgr.connect(ws))

    assert ws.accepted
    assert mgr.active_count == 1


def test_broadcast_sends_to_all_clients():
    mgr = ConnectionManager()
    a, b = FakeWebSocket(), FakeWebSocket()
    message = {"type": "insight_detected", "data": {"id": "abc"}}

    async def scenario():
        await mgr.connect(a)
        await mgr.connect(b)
        await mgr.broadcast(message)

    asyncio.run(scenario())

    assert a.sent == [message]
    assert b.sent == [message]


def test_broadcast_prunes_dead_connections():
    mgr = ConnectionManager()
    good, bad = FakeWebSocket(), FakeWebSocket(fail_on_send=True)

    async def scenario():
        await mgr.connect(good)
        await mgr.connect(bad)
        await mgr.broadcast({"hello": "world"})

    asyncio.run(scenario())

    # The failing client is dropped; the healthy one still received the message.
    assert mgr.active_count == 1
    assert good.sent == [{"hello": "world"}]


def test_disconnect_removes_client():
    mgr = ConnectionManager()
    ws = FakeWebSocket()

    async def scenario():
        await mgr.connect(ws)
        await mgr.disconnect(ws)

    asyncio.run(scenario())

    assert mgr.active_count == 0
