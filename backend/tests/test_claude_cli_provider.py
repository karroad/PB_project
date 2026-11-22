"""The claude_cli content provider drives the Claude Code CLI (headless) so content runs on the
monthly subscription. The subprocess is faked — no real CLI call."""
import asyncio
import json

import pytest

from app.ai import llm


def _use_cli(monkeypatch, fake_stdout):
    async def fake_run(args, stdin, timeout):
        assert args[0] == llm.settings.CLAUDE_CLI_BIN and "-p" in args and "--output-format" in args
        assert "--append-system-prompt" in args  # system prompt is passed through
        return fake_stdout
    monkeypatch.setattr(llm, "_run_cli", fake_run)
    monkeypatch.setattr(llm.settings, "AI_PROVIDER", "claude_cli")
    llm.reset_providers()


def test_claude_cli_extracts_result(monkeypatch):
    payload = {"type": "result", "subtype": "success", "result": '{"site_name": "Alpine Co"}', "total_cost_usd": 0.0}
    _use_cli(monkeypatch, json.dumps(payload))
    prov = llm.get_provider()
    assert prov.name == "claude-cli" and prov.offline is False
    out = asyncio.run(prov.complete("system here", "write json"))
    assert out == '{"site_name": "Alpine Co"}'


def test_generate_json_via_claude_cli(monkeypatch):
    payload = {"type": "result", "subtype": "success", "result": '{"theme": "forest", "extra": "x"}'}
    _use_cli(monkeypatch, json.dumps(payload))
    data, source = asyncio.run(llm.generate_json("tester", "make it", {"theme": "default", "keep": 1}))
    assert source == "claude-cli"
    assert data["theme"] == "forest" and data["keep"] == 1  # merged over the fallback, types kept


def test_claude_cli_error_surfaces(monkeypatch):
    _use_cli(monkeypatch, json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "boom"}))
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.get_provider().complete("s", "p"))


def teardown_function():
    llm.reset_providers()  # don't leak the patched provider into other tests
