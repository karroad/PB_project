"""Error taxonomy used by agents, adapters and the orchestrator.

* RetryableError  — transient (network, rate limit, provider 5xx). Retried with backoff.
* PipelineError   — permanent (bad config, quality gate, rejected approval). Fails the step
                    with an error code and a human hint shown in the dashboard.
* ApprovalRequired — not an error: pauses the job until a user approves the action.
"""
from __future__ import annotations

import asyncio

import httpx


class PipelineError(Exception):
    retryable = False

    def __init__(self, message: str, code: str = "pipeline_error", hint: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"message": self.message, "code": self.code, "hint": self.hint, "retryable": self.retryable, "details": self.details}


class RetryableError(PipelineError):
    retryable = True


class ConfigurationError(PipelineError):
    def __init__(self, message: str, hint: str | None = None, **kw):
        super().__init__(message, code="configuration_error", hint=hint, **kw)


class QualityGateError(PipelineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="quality_gate_failed",
                         hint="Fix the critical checks listed in the quality report, then retry the job.", details=details)


class ApprovalRequired(Exception):
    def __init__(self, action: str, description: str, details: dict | None = None):
        super().__init__(description)
        self.action = action
        self.description = description
        self.details = details or {}


class JobCancelled(Exception):
    pass


def classify(exc: BaseException) -> PipelineError:
    """Map any exception to a PipelineError so it can be stored and shown consistently."""
    if isinstance(exc, PipelineError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return RetryableError("The step timed out", code="timeout", hint="The provider was slow; the step will be retried.")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text[:300]
        if status in (408, 409, 425, 429) or status >= 500:
            return RetryableError(f"Provider returned HTTP {status}", code=f"http_{status}", details={"body": body})
        hint = "Check the provider credentials and permissions." if status in (401, 403) else None
        return PipelineError(f"Provider returned HTTP {status}: {body}", code=f"http_{status}", hint=hint)
    if isinstance(exc, httpx.TransportError):
        return RetryableError(f"Network error: {exc.__class__.__name__}", code="network_error")
    if exc.__class__.__name__ == "LLMError":
        msg = str(exc)
        retry = any(w in msg.lower() for w in ("rate", "reach", "error 5", "overloaded"))
        return (RetryableError if retry else PipelineError)(msg, code="ai_error")
    if isinstance(exc, (FileNotFoundError, PermissionError, OSError)):
        return PipelineError(f"File system error: {exc}", code="filesystem_error", hint="Check disk space and permissions of the data directory.")
    return PipelineError(f"Unexpected error: {exc.__class__.__name__}: {exc}", code="internal_error",
                         hint="This looks like a bug. The full traceback was recorded in the job events.")
