"""Stack adapter registry. Add a new technology by implementing StackAdapter and registering it here."""
from .base import StackAdapter, StackInfo
from .nextjs import NextJSAdapter
from .others import LaravelAdapter, StaticAdapter, WordPressAdapter

STACKS: dict[str, StackAdapter] = {a.info.key: a for a in (NextJSAdapter(), WordPressAdapter(), LaravelAdapter(), StaticAdapter())}

PLANNED = [
    StackInfo(key="astro", name="Astro", intended_use="Content sites", description="Planned adapter", deploy_model="static", status="planned"),
    StackInfo(key="django", name="Django", intended_use="Python web apps", description="Planned adapter", deploy_model="docker", status="planned"),
]


def get_stack(key: str) -> StackAdapter:
    if key not in STACKS:
        raise KeyError(f"Unknown stack '{key}'")
    return STACKS[key]


def catalog() -> list[dict]:
    return [a.info.dict() for a in STACKS.values()] + [p.dict() for p in PLANNED]
