"""Sanitized provider-failure classification for the RM-04 durable live gate.

This test-only helper projects a raised provider/runtime exception into a short,
deterministic classification token suitable for diagnostics.  It deliberately
uses **only** structural facts:

- HTTP status code (an integer attribute), and
- exception class names.

It never reads ``str(exc)`` and never inspects messages, request/response bodies,
headers, URLs, prompts or credentials, so a classification derived here cannot
leak provider reasoning, request content or secrets.

Classification vocabulary (used by the DeepSeek qualification runbook):

    AUTH
    RATE_LIMIT
    NETWORK
    TIMEOUT
    PROVIDER_4XX
    PROVIDER_5XX
    PROVIDER_API
    RUNTIME
    UNKNOWN
"""

from __future__ import annotations

from collections.abc import Iterator

__all__ = ["classify_provider_failure"]


def _cause_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc`` and each distinct exception reachable via cause/context."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _classify_status(status: int) -> str | None:
    if status in (401, 403):
        return f"AUTH (status={status})"
    if status == 429:
        return f"RATE_LIMIT (status={status})"
    if 500 <= status <= 599:
        return f"PROVIDER_5XX (status={status})"
    if 400 <= status <= 499:
        return f"PROVIDER_4XX (status={status})"
    return None


def _classify_name(name: str) -> str | None:
    if "Timeout" in name:
        return f"TIMEOUT ({name})"
    if "Connect" in name or "Network" in name or "Transport" in name:
        return f"NETWORK ({name})"
    return None


def classify_provider_failure(exc: BaseException) -> str:
    """Return a sanitized classification token for ``exc``.

    The returned string contains at most a classification label, an HTTP status
    integer and an exception class name.  No exception message, provider body,
    header, URL, prompt or credential is ever included.
    """
    chain = list(_cause_chain(exc))

    # 1. Prefer the most specific structurally observable signal: an HTTP status.
    for current in chain:
        status = getattr(current, "status_code", None)
        if isinstance(status, int):
            classified = _classify_status(status)
            if classified is not None:
                return classified

    # 2. Network/timeout transport failures (class-name structural signal).
    for current in chain:
        classified = _classify_name(type(current).__name__)
        if classified is not None:
            return classified

    # 3. Provider API failure without an observable status.
    for current in chain:
        if type(current).__name__ == "ModelAPIError":
            return "PROVIDER_API (ModelAPIError)"

    # 4. Project runtime wrapper (the RM-03 runtime raises ModelError on failure).
    for current in chain:
        if type(current).__name__ == "ModelError":
            return "RUNTIME (ModelError)"

    return f"UNKNOWN ({type(exc).__name__})"
