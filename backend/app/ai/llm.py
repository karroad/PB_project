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


class ClaudeCliProvider(TextProvider):
    """Drives the Claude Code CLI in headless/print mode, so content runs on the monthly
    Claude subscription (Pro/Max) instead of a metered API key. Requires the `claude` CLI
    installed and logged in (OAuth) on the machine the backend runs on (e.g. server 65/116)."""

    name = "claude-cli"
    offline = False

    async def complete(self, system: str, prompt: str) -> str:
        args = [settings.CLAUDE_CLI_BIN, "-p", "--output-format", "json", "--append-system-prompt", system]
        if settings.CLAUDE_CLI_MODEL:
            args += ["--model", settings.CLAUDE_CLI_MODEL]
        out = await _run_cli(args, prompt, settings.CLAUDE_CLI_TIMEOUT)
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return out  # some versions print the raw answer when not asked for json
        if isinstance(data, dict):
            if data.get("is_error") or (data.get("type") == "result" and data.get("subtype") not in (None, "success")):
                raise LLMError(f"Claude CLI error: {str(data.get('result') or data.get('subtype'))[:200]}")
            return data.get("result", "") or ""
        return out


async def _run_cli(args: list[str], stdin: str, timeout: int) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as e:
        raise LLMError(f"Claude CLI not found ({args[0]}); install it and `claude login` on this machine") from e
    try:
        so, se = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise LLMError("Claude CLI timed out")
    if proc.returncode != 0:
        raise LLMError(f"Claude CLI failed ({proc.returncode}): {se.decode(errors='ignore')[:300] or so.decode(errors='ignore')[:300]}")
    return so.decode(errors="ignore").strip()


_provider: TextProvider | None = None
_ai_semaphore = asyncio.Semaphore(settings.AI_MAX_CONCURRENT_REQUESTS)


# --------------------------------------------------------------------------- code provider
class CodeProvider:
    """Writes the actual site code (HTML/CSS/JS). Separate from the content provider so the client
    can use a cheaper coding model (z.ai GLM Coding Plan) for the heavy code generation."""

    name = "offline"
    offline = True

    async def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class OfflineCodeProvider(CodeProvider):
    name = "offline"
    offline = True

    async def complete(self, system: str, prompt: str) -> str:
        return ""


class ZaiCodeProvider(CodeProvider):
    """Calls z.ai's Anthropic-compatible Messages endpoint (the GLM Coding Plan endpoint)."""

    name = "zai"
    offline = False

    async def complete(self, system: str, prompt: str) -> str:
        import httpx

        url = settings.ZAI_BASE_URL.rstrip("/") + "/v1/messages"
        headers = {"Authorization": f"Bearer {settings.ZAI_API_KEY}", "x-api-key": settings.ZAI_API_KEY,
                   "anthropic-version": "2023-06-01", "content-type": "application/json"}
        # GLM Flash enables "thinking" by default, which burns the whole token budget and ~150s
        # per call on reasoning and emits little/no code (hits max_tokens with 0 output). Disabling
        # it makes code generation fast (~30s) and actually return the HTML/CSS.
        body = {"model": settings.ZAI_MODEL, "max_tokens": settings.CODE_MAX_TOKENS,
                "system": system, "messages": [{"role": "user", "content": prompt}],
                "thinking": {"type": "disabled"}}
        try:
            async with httpx.AsyncClient(timeout=settings.CODE_TIMEOUT_SECONDS) as c:
                r = await c.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"Could not reach the code model (z.ai): {e.__class__.__name__}") from e
        if r.status_code == 401:
            raise LLMError("Code model authentication failed — check ZAI_API_KEY")
        if r.status_code == 429:
            raise LLMError("Code model rate limited / quota exhausted")
        if r.status_code >= 400:
            raise LLMError(f"Code model error {r.status_code}: {r.text[:300]}")
        data = r.json()
        if data.get("stop_reason") == "max_tokens":
            raise LLMError("Code model response was truncated (raise CODE_MAX_TOKENS)")
        parts = [b.get("text", "") for b in (data.get("content") or []) if b.get("type") == "text"]
        text = "".join(parts).strip()
        if not text:
            raise LLMError("Code model returned no content")
        return text


class AnthropicCodeProvider(CodeProvider):
    """Stopgap: use the Claude (Anthropic) key to write code too, when z.ai has no balance.
    Higher cost than the z.ai Coding Plan, but produces the same unique AI-authored sites."""

    name = "anthropic"
    offline = False

    def __init__(self) -> None:
        self._p = AnthropicProvider()

    async def complete(self, system: str, prompt: str) -> str:
        return await self._p.complete(system, prompt)


_code_provider: CodeProvider | None = None


def get_code_provider() -> CodeProvider:
    global _code_provider
    if _code_provider is None:
        choice = settings.CODE_PROVIDER.lower()
        if not settings.AI_CODE_GENERATION:
            _code_provider = OfflineCodeProvider()
        elif choice == "anthropic" and settings.ANTHROPIC_API_KEY:
            _code_provider = AnthropicCodeProvider()
        elif choice == "zai" or (choice == "auto" and settings.ZAI_API_KEY):
            _code_provider = ZaiCodeProvider() if settings.ZAI_API_KEY else OfflineCodeProvider()
        else:
            _code_provider = OfflineCodeProvider()
    return _code_provider


def reset_providers() -> None:
    """Drop cached providers so a settings change (e.g. CODE_PROVIDER) takes effect."""
    global _provider, _code_provider
    _provider = _code_provider = None


async def complete_code(system: str, prompt: str) -> str:
    """Raw completion from the code model (not JSON). Raises LLMError on failure."""
    provider = get_code_provider()
    if provider.offline:
        raise LLMError("No code model configured")
    async with _ai_semaphore:
        return await provider.complete(system, prompt)


def get_provider() -> TextProvider:
    global _provider
    if _provider is None:
        choice = settings.AI_PROVIDER.lower()
        if choice == "claude_cli":
            _provider = ClaudeCliProvider()
        elif choice == "anthropic" or (choice == "auto" and settings.ANTHROPIC_API_KEY):
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
