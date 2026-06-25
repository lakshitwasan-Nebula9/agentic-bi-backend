"""Event-type names for the real-time (WebSocket) layer.

Kept in one place so the publisher (``insight_service``) and the Redis listener
agree on the stream name. Mirrors the snake_case convention used by the agent
pipeline events in ``app/agents``.
"""

# Emitted onto Redis Streams (``events:insight_detected``) whenever the Insight
# Agent persists a new InsightEvent. The WebSocket listener tails this stream and
# pushes each insight to connected frontend clients.
INSIGHT_DETECTED = "insight_detected"
