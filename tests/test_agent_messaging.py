import uuid

import pytest
import redis

from app.agents.messaging import AgentEvent, AgentPublisher, AgentSubscriber, stream_name


@pytest.fixture
def redis_client():
    client = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError:
        pytest.skip("Redis is not available at localhost:6379")
    yield client


@pytest.fixture
def event_type():
    return f"test.event.{uuid.uuid4().hex}"


class RecordingSubscriber(AgentSubscriber):
    def __init__(self, *args, **kwargs):
        self.received: list[AgentEvent] = []
        super().__init__(*args, **kwargs)

    def handle_event(self, event: AgentEvent) -> None:
        self.received.append(event)


def test_publish_and_consume_event(redis_client, event_type):
    publisher = AgentPublisher(redis_client=redis_client)
    subscriber = RecordingSubscriber(
        group_name="test-group",
        consumer_name="test-consumer",
        event_types=[event_type],
        redis_client=redis_client,
    )

    publisher.publish(event_type, {"foo": "bar"})

    processed = subscriber.poll_once(block_ms=1000)

    assert processed == 1
    assert len(subscriber.received) == 1
    event = subscriber.received[0]
    assert event.event_type == event_type
    assert event.payload == {"foo": "bar"}


def test_consumer_group_does_not_redeliver_acked_messages(redis_client, event_type):
    publisher = AgentPublisher(redis_client=redis_client)
    subscriber = RecordingSubscriber(
        group_name="test-group",
        consumer_name="test-consumer",
        event_types=[event_type],
        redis_client=redis_client,
    )

    publisher.publish(event_type, {"foo": "bar"})
    subscriber.poll_once(block_ms=1000)

    processed_again = subscriber.poll_once(block_ms=100)
    assert processed_again == 0


def test_each_event_type_uses_its_own_stream(event_type):
    assert stream_name(event_type) == f"events:{event_type}"
