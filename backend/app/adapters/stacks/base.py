from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from ...renderer.site_renderer import render_static

LogFn = Callable[[str], Awaitable[None]]


@dataclass
class StackInfo:
    key: str
    name: str
    intended_use: str
    description: str
    deploy_model: str  # static | docker | saas
    status: str = "available"  # available | beta | planned
    versions: list[str] = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)


class StackAdapter:
    """A stack adapter turns the shared site spec into a stack-specific project (source)
    plus a static build artefact used for testing, previews and static hosting."""

    info: StackInfo

    def scaffold(self, spec: dict, source_dir: Path) -> list[str]:
        raise NotImplementedError

    async def build(self, spec: dict, source_dir: Path, build_dir: Path, media_dir: Path, base_url: str, slug: str, log: LogFn) -> list[str]:
        await log("Rendering production pages from the content model")
        return render_static(spec, build_dir, media_dir, base_url, slug)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def write_files(root: Path, files: dict[str, str]) -> list[str]:
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return list(files)

    @staticmethod
    def site_json(spec: dict) -> str:
        keys = ("requirements", "plan", "brand", "content", "seo", "images")
        return json.dumps({k: spec[k] for k in keys if k in spec}, indent=2, ensure_ascii=False)
