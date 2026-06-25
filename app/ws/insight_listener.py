"""Background task: tail the insight Redis Stream and fan out to WebSocket clients.

Uses ``redis.asyncio`` so the blocking ``XREAD`` never stalls the event loop.
We tail with a plain ``XREAD`` from ``$`` (new messages only) rather than a
consumer group — this is a live push, not durable work that needs acking, and
every worker should receive every message to forward to its own clients.
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.agents.messaging import stream_name
from app.core.config import settings
from app.ws.connection_manager import connection_manager
from app.ws.events import INSIGHT_DETECTED

logger = logging.getLogger(__name__)


async def run_insight_listener() -> None:
    """Forward each new insight event to all connected WebSocket clients.

    Runs until cancelled (on app shutdown). Transient Redis errors are retried
    so a flaky broker doesn't kill real-time delivery.
    """
    stream = stream_name(INSIGHT_DETECTED)
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    last_id = "$"  # only messages produced after the listener starts

    logger.info("Insight WebSocket listener started on stream '%s'", stream)
    try:
        while True:
            try:
                response = await client.xread({stream: last_id}, block=5000, count=10)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep listening through transient broker errors
                logger.warning("Insight listener read failed; retrying", exc_info=True)
                await asyncio.sleep(1.0)
                continue

            for _stream, messages in response or []:
                for message_id, fields in messages:
                    last_id = message_id
                    try:
                        payload = json.loads(fields["payload"])
                    except (KeyError, json.JSONDecodeError):
                        logger.warning("Skipping malformed insight event %s", message_id)
                        continue
                    await connection_manager.broadcast({"type": INSIGHT_DETECTED, "data": payload})
    except asyncio.CancelledError:
        logger.info("Insight WebSocket listener stopped")
        raise
    finally:
        await client.aclose()
