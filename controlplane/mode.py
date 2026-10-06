"""Process tools mode, with a per-request override for d2c_test_ keys."""
from __future__ import annotations

import contextvars
import os

_override: contextvars.ContextVar[str | None] = contextvars.ContextVar("d2c_tools_mode", default=None)


def current_tools_mode() -> str:
    forced = _override.get()
    if forced:
        return forced
    return os.getenv("TOOLS_MODE", "mock").strip().lower() or "mock"


def force_tools_mode(mode: str | None):
    return _override.set(mode)


def reset_tools_mode(token) -> None:
    _override.reset(token)
