"""Environment invariants checked before accepting production traffic."""
from __future__ import annotations

import os


def production() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "production"


def legacy_headers_allowed() -> bool:
    return not production() and os.getenv("ALLOW_LEGACY_ACTOR_HEADERS", "0") == "1"


def validate_environment() -> None:
    if not production():
        return
    errors = []
    if not os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql")):
        errors.append("production requires PostgreSQL DATABASE_URL")
    if len(os.getenv("OPS_SESSION_SECRET", "")) < 32:
        errors.append("OPS_SESSION_SECRET must contain at least 32 characters")
    if not os.getenv("CREDENTIAL_ENCRYPTION_KEYS"):
        errors.append("CREDENTIAL_ENCRYPTION_KEYS is required")
    if not os.getenv("PUBLIC_APP_URL", "").startswith("https://"):
        errors.append("PUBLIC_APP_URL must use https")
    if os.getenv("ALLOW_LEGACY_ACTOR_HEADERS") == "1":
        errors.append("legacy actor headers are forbidden in production")
    if os.getenv("LLM_PROVIDER", "openai") == "openai" and not os.getenv("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY is required for the selected model provider")
    if os.getenv("LIVE_REFUNDS_ENABLED") == "1" and os.getenv("PAYMENT_INTEGRATION_VERIFIED") != "1":
        errors.append("live refunds require PAYMENT_INTEGRATION_VERIFIED after merchant integration validation")
    if errors:
        raise RuntimeError("; ".join(errors))
    from controlplane.vault import _cipher
    _cipher()  # validate configured encryption keys before accepting traffic


def cookie_secure() -> bool:
    return production() or os.getenv("COOKIE_SECURE") == "1"
