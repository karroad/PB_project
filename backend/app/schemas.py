from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def clean_domain(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not DOMAIN_RE.match(v):
        raise ValueError("Invalid domain name")
    return v


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"  # permissive: allows internal domains such as .local


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    name: str = ""
    password: str = Field(min_length=8)
    role: str = Field(default="operator", pattern="^(admin|operator|viewer)$")


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = Field(default=None, pattern="^(admin|operator|viewer)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class WebsiteCreate(BaseModel):
    prompt: str = Field(min_length=10, max_length=4000)
    name: str | None = Field(default=None, max_length=120)
    # Both are explicit user choices (confirmed requirement): no AI auto-selection.
    stack: str = Field(min_length=1, description="Technology chosen by the user, e.g. nextjs | wordpress | laravel | static")
    hosting_provider: str = "local"
    hosting_account_id: str | None = None
    dns_provider: str = Field(default="none", description="Optional default for the Publish step: cloudflare | ovh | none")
    dns_account_id: str | None = None
    domain: str | None = None
    # buy: purchase the domain through the chosen provider's API · existing: a domain already in that account
    domain_mode: Literal["buy", "existing"] | None = None
    require_approval: bool = False
    # Optional: a public website the generator takes design + structure inspiration from (never copies).
    reference_url: str | None = Field(default=None, max_length=2000)

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str | None) -> str | None:
        return clean_domain(v)

    @field_validator("reference_url")
    @classmethod
    def _reference(cls, v: str | None) -> str | None:
        if not v or not v.strip():
            return None
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        if len(v) > 2000:
            raise ValueError("Reference URL is too long")
        return v


class WebsiteUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    domain: str | None = None
    hosting_provider: str | None = None
    hosting_account_id: str | None = None
    dns_provider: str | None = None
    dns_account_id: str | None = None
    require_approval: bool | None = None
    env: dict[str, str] | None = None

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str | None) -> str | None:
        return clean_domain(v)


class PublishRequest(BaseModel):
    """Chosen when the user publishes the reviewed preview."""
    hosting_provider: str = "local"
    hosting_account_id: str | None = None
    server_id: str | None = None  # when hosting_provider == "server"
    dns_provider: str = Field(min_length=1, description="Domain provider chosen by the user: cloudflare | ovh | none (platform URL)")
    dns_account_id: str | None = None
    domain: str | None = None
    domain_mode: Literal["buy", "existing"] | None = None

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str | None) -> str | None:
        return clean_domain(v)


class ChangeRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)


class DeleteConfirm(BaseModel):
    confirm: str


class ProviderCreate(BaseModel):
    provider: str
    kind: str = Field(pattern="^(dns|hosting|registrar|commerce|ai)$")
    label: str = Field(min_length=1, max_length=120)
    credentials: dict[str, str]
    meta: dict = {}
    max_sites: int | None = Field(default=None, ge=1)


class RecommendIn(BaseModel):
    prompt: str = Field(min_length=3)


class DecisionIn(BaseModel):
    comment: str | None = None
