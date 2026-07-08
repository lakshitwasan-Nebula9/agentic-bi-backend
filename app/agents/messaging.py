import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis

from app.core.config import settings

STREAM_PREFIX = "events:"

# Event type the Insight Agent emits when it persists a new InsightEvent. The SSE
# endpoint tails this stream to push insights to the frontend in real time, and the
# Explainability Agent consumes it to build receipts.
INSIGHT_DETECTED = "insight_detected"

# Emitted when a dashboard permission is granted, changed, or revoked. The SSE
# endpoint (GET /dashboards/stream) tails this stream and forwards each event to
# the affected user so their UI refreshes access without a manual reload.
DASHBOARD_PERMISSION_CHANGED = "dashboard_permission_changed"


def stream_name(event_type: str) -> str:
    return f"{STREAM_PREFIX}{event_type}"


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


@dataclass
class AgentEvent:
    message_id: str
    event_type: str
    event_id: str
    produced_at: str
    payload: dict[str, Any]


class AgentPublisher:
    """Publishes agent pipeline events onto per-event-type Redis Streams."""

    def __init__(self, redis_client: redis.Redis | None = None) -> None:
        self._redis = redis_client or get_redis_client()

    def publish(self, event_type: str, payload: dict[str, Any]) -> str:
        fields = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "produced_at": datetime.now(UTC).isoformat(),
            "payload": json.dumps(payload),
        }
        return self._redis.xadd(stream_name(event_type), fields)


class AgentSubscriber(ABC):
    """Base class for agent workers that consume specific event types via Redis Streams consumer groups."""

    def __init__(
        self,
        group_name: str,
        consumer_name: str,
        event_types: Iterable[str],
        redis_client: redis.Redis | None = None,
    ) -> None:
        self._redis = redis_client or get_redis_client()
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.event_types = list(event_types)
        self._ensure_consumer_groups()

    def _ensure_consumer_groups(self) -> None:
        for event_type in self.event_types:
            try:
                self._redis.xgroup_create(
                    stream_name(event_type), self.group_name, id="0", mkstream=True
                )
            except redis.ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    @abstractmethod
    def handle_event(self, event: AgentEvent) -> None:
        """Process a single event. Implemented by each agent worker."""

    def poll_once(self, block_ms: int = 5000, count: int = 10) -> int:
        streams = {stream_name(event_type): ">" for event_type in self.event_types}
        response = self._redis.xreadgroup(
            self.group_name, self.consumer_name, streams, count=count, block=block_ms
        )

        processed = 0
        for stream, messages in response or []:
            for message_id, fields in messages:
                event = AgentEvent(
                    message_id=message_id,
                    event_type=fields["event_type"],
                    event_id=fields["event_id"],
                    produced_at=fields["produced_at"],
                    payload=json.loads(fields["payload"]),
                )
                self.handle_event(event)
                self._redis.xack(stream, self.group_name, message_id)
                processed += 1

        return processed

    def run(self, block_ms: int = 5000, count: int = 10) -> None:
        while True:
            self.poll_once(block_ms=block_ms, count=count)
