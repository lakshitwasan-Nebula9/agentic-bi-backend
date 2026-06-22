"""
Langfuse observability client — disabled when keys are not configured.

Usage (Langfuse 3.x context-manager API):
    from contextlib import nullcontext
    lf = get_langfuse()
    with (lf.start_as_current_observation(as_type="trace", name="my_trace") if lf else nullcontext()) as trace:
        with (lf.start_as_current_observation(as_type="generation", name="llm_call", model="...") if lf else nullcontext()) as gen:
            if gen:
                gen.update(input=prompt)
            # ... call LLM ...
            if gen:
                gen.update(output=response_text)
"""

import logging
import os

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None


def get_langfuse():
    """Return a Langfuse client, or None if Langfuse is not configured."""
    global _client

    if not settings.LANGFUSE_SECRET_KEY or not settings.LANGFUSE_PUBLIC_KEY:
        return None

    if _client is None:
        try:
            os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.LANGFUSE_SECRET_KEY)
            os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.LANGFUSE_PUBLIC_KEY)
            os.environ.setdefault("LANGFUSE_BASE_URL", settings.LANGFUSE_BASE_URL)

            from langfuse import get_client

            _client = get_client()
            logger.info("Langfuse client initialised (host=%s)", settings.LANGFUSE_BASE_URL)
        except Exception:
            logger.warning("Failed to initialise Langfuse client", exc_info=True)
            return None

    return _client
