"""Configurable AI text provider layer.

Providers implement `complete(system, prompt) -> str`. `generate_json` asks for JSON,
parses it defensively, and deep-merges it over a deterministic fallback so missing or
mistyped fields never reach the generators. Add another provider by subclassing
`TextProvider` and registering it in `get_provider`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from ..config import settings

log = logging.getLogger("siteforge.llm")


class LLMError(RuntimeError):
    pass


class TextProvider:
    name = "base"
    offline = False

    async def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class OfflineProvider(TextProvider):
    name = "offline"
    offline = True

    async def complete(self, system: str, prompt: str) -> str:
        return "{}"


class AnthropicProvider(TextProvider):
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        # api_key=None lets the SDK resolve credentials (env var, auth token or `ant auth login` profile)
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY or None, max_retries=4)

    async def complete(self, system: str, prompt: str) -> str:
        a = self._anthropic
        try:
            async with self.client.beta.messages.stream(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=32000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # server-side fallback model if a request is declined
                output_config={"effort": settings.ANTHROPIC_EFFORT},
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = await stream.get_final_message()
        except a.RateLimitError as e:
            raise LLMError(f"AI provider rate limited: {e.message}") from e
        except a.AuthenticationError as e:
            raise LLMError("AI provider authentication failed — check ANTHROPIC_API_KEY") from e
        except a.APIStatusError as e:
            raise LLMError(f"AI provider error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("Could not reach AI provider") from e
        if message.stop_reason == "refusal":
            raise LLMError("AI provider declined the request")
        if message.stop_reason == "max_tokens":
            raise LLMError("AI response was truncated")
        return "".join(b.text for b in message.content if b.type == "text")


_provider: TextProvider | None = None
_ai_semaphore = asyncio.Semaphore(settings.AI_MAX_CONCURRENT_REQUESTS)


def get_provider() -> TextProvider:
    global _provider
    if _provider is None:
        choice = settings.AI_PROVIDER.lower()
        if choice == "anthropic" or (choice == "auto" and settings.ANTHROPIC_API_KEY):
            try:
                _provider = AnthropicProvider()
            except Exception as e:  # SDK missing / misconfigured
                log.warning("Anthropic provider unavailable (%s); using offline generator", e)
                _provider = OfflineProvider()
        else:
            _provider = OfflineProvider()
    return _provider


def extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("No JSON object in AI response")
    return json.loads(text[start : end + 1])


def merge(fallback, value):
    """Deep-merge AI output over fallback, keeping fallback types."""
    if isinstance(fallback, dict) and isinstance(value, dict):
        out = dict(fallback)
        for k, v in value.items():
            out[k] = merge(fallback[k], v) if k in fallback else v
        return out
    if isinstance(fallback, list):
        if isinstance(value, list) and value:
            if fallback and isinstance(fallback[0], dict):
                return [merge(fallback[min(i, len(fallback) - 1)], v) if isinstance(v, dict) else fallback[min(i, len(fallback) - 1)] for i, v in enumerate(value)]
            return value
        return fallback
    if fallback is None or value is None:
        return value if value is not None else fallback
    if isinstance(fallback, bool):
        return value if isinstance(value, bool) else fallback
    if isinstance(fallback, (int, float)) and isinstance(value, (int, float)):
        return value
    if isinstance(fallback, str) and isinstance(value, str) and value.strip():
        return value
    return fallback


SYSTEM_BASE = (
    "You are one specialised agent inside an automated website factory. "
    "Reply with a single JSON object only — no prose, no markdown fences. "
    "Keep the exact keys and value types of the example you are given. "
    "Write original, factually careful content; never invent statistics, awards, testimonials or credentials."
)


def _fit(obj: dict, limit: int) -> str:
    """Serialise for the prompt — never cut JSON mid-way (a truncated example makes the model's job impossible)."""
    text = json.dumps(obj, ensure_ascii=False)
    if len(text) > limit:
        raise LLMError(f"Spec too large for one request ({len(text)} > {limit} chars)")
    return text


async def generate_json(role: str, instruction: str, fallback: dict, context: dict | None = None, limit: int = 60_000) -> tuple[dict, str]:
    """Returns (result, source) where source is the provider name or 'offline'."""
    provider = get_provider()
    if provider.offline:
        return fallback, "offline"
    prompt = (
        f"{instruction}\n\nContext:\n{_fit(context or {}, limit)}\n\n"
        f"Return JSON with exactly this shape (values are examples to improve on):\n{_fit(fallback, limit)}"
    )
    async with _ai_semaphore:
        raw = await provider.complete(f"{SYSTEM_BASE}\nRole: {role}", prompt)
    try:
        data = extract_json(raw)
    except (LLMError, json.JSONDecodeError) as e:
        raise LLMError(f"Unparseable AI response: {e}") from e
    return merge(fallback, data), provider.name
