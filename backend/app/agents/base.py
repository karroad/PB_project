from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..ai.llm import generate_json, get_provider
from ..config import settings
from ..errors import ApprovalRequired

if TYPE_CHECKING:
    from ..orchestrator.recorder import Recorder


@dataclass
class SiteInfo:
    id: str
    slug: str
    name: str
    prompt: str
    stack: str
    domain: str | None
    hosting_provider: str
    hosting_account_id: str | None
    dns_provider: str
    dns_account_id: str | None
    require_approval: bool
    current_deployment_id: str | None
    status: str = "draft"

    @property
    def workspace(self) -> Path:
        return settings.sites_dir / self.slug

    @property
    def media_dir(self) -> Path:
        return self.workspace / "media"


@dataclass
class StepContext:
    recorder: "Recorder"
    step_key: str
    site: SiteInfo
    state: dict
    approvals: dict[str, str]
    site_updates: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)  # job parameters, e.g. the change-request instruction

    @property
    def offline(self) -> bool:
        return get_provider().offline

    async def log(self, message: str, level: str = "info", progress: float | None = None, data: dict | None = None) -> None:
        await self.recorder.log(self.step_key, message, level=level, progress=progress, data=data)
        if self.offline and settings.SIMULATED_STEP_DELAY > 0:
            await asyncio.sleep(settings.SIMULATED_STEP_DELAY)

    async def progress(self, pct: float) -> None:
        await self.recorder.progress(self.step_key, pct)

    def require_approval(self, action: str, description: str, details: dict | None = None) -> None:
        if self.approvals.get(action) == "approved":
            return
        raise ApprovalRequired(action, description, details)

    def update_site(self, **fields: Any) -> None:
        self.site_updates.update(fields)
        for k, v in fields.items():
            if hasattr(self.site, k):
                setattr(self.site, k, v)

    def credentials(self, account_id: str | None) -> dict:
        return self.recorder.credentials(account_id)

    async def ai_json(self, role: str, instruction: str, fallback: dict, context: dict | None = None, limit: int = 60_000) -> dict:
        """AI call with graceful degradation: provider failures fall back to the deterministic generator."""
        try:
            data, source = await generate_json(role, instruction, fallback, context, limit)
        except Exception as e:  # noqa: BLE001 — every AI failure is non-fatal here
            await self.log(f"AI provider unavailable ({e}); using built-in generator", level="warning")
            return fallback
        if source != "offline":
            await self.log(f"Generated with {source}")
        return data


class Agent:
    key = "base"
    title = "Step"
    agent_name = "Agent"
    description = ""

    async def run(self, ctx: StepContext) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


def kv(*pairs: tuple[str, Any]) -> dict:
    return {"type": "kv", "items": [{"label": k, "value": v} for k, v in pairs]}


def chips(label: str, items: list[str]) -> dict:
    return {"type": "chips", "label": label, "items": items}
