"""
LLM client for the Copilot service.

Uses Claude Haiku via the Anthropic SDK.
Only the Copilot uses this — all other agents still use Gemini via google-adk.
"""

import json
import logging

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic | None:
    global _client
    if _client is None and settings.ANTHROPIC_API_KEY:
        _client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


async def generate_text(prompt: str, system_instruction: str | None = None) -> str | None:
    """Call Claude Haiku and return plain text. Returns None on failure."""
    client = _get_client()
    if client is None:
        logger.warning("Anthropic not configured (ANTHROPIC_API_KEY missing) — skipping LLM call")
        return None

    try:
        kwargs = dict(
            model=settings.COPILOT_LLM_MODEL,
            max_tokens=2048,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        if system_instruction:
            kwargs["system"] = system_instruction

        response = await client.messages.create(**kwargs)
        return response.content[0].text
    except Exception:
        logger.warning("Claude Haiku call failed", exc_info=True)
        return None


async def generate_json(prompt: str, system_instruction: str | None = None) -> dict | None:
    """Call Claude Haiku expecting a JSON response. Returns None on failure."""
    text = await generate_text(prompt, system_instruction)
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Claude Haiku returned non-JSON: %r", cleaned[:200])
        return None
