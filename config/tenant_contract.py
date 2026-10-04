"""Platform tenant contract.

A tenant is a folder under ``tenants/<id>/``. ``tenant.yaml`` is the platform
file (auth ladder, refund caps, channels, versions). The legacy brand file
``config/tenants/<id>/config.yaml`` stays in place for QA tone and prompts.

Missing platform files do not crash boot: the loader returns a default
contract, and a missing policy file returns an empty mapping.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

AuthLevel = Literal["anonymous", "identified", "verified"]

_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_POLICY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_REPO_ROOT = Path(__file__).resolve().parents[1]


class AuthPolicy(BaseModel):
    """Minimum auth level required before an intent may proceed."""

    model_config = ConfigDict(extra="ignore")

    intents: Dict[str, AuthLevel] = Field(
        default_factory=lambda: {
            "policy": "anonymous",
            "order_status": "identified",
            "refund": "verified",
            "return": "identified",
            "cancel": "identified",
        }
    )


class TenantLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    auto_refund_max: float = 2000
    manager_refund_max: float = 10000
    live_refund_cap_inr: float = 20000
    photo_required_for: List[str] = Field(
        default_factory=lambda: ["damaged", "missing_item"]
    )


class ToolFlags(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shopify: bool = False
    stripe: bool = False
    gmail: bool = False


class ContractVersions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent: str = "0.0.0"
    policy_pack: str = "unversioned"
    knowledge_snapshot: str = "none"


class PlatformTenant(BaseModel):
    """Parsed ``tenants/<id>/tenant.yaml``. Defaults keep boot alive."""

    model_config = ConfigDict(extra="ignore")

    id: str
    brand: str = ""
    tone: str = ""
    locale: str = "en"
    currency: str = "USD"
    auth: AuthPolicy = Field(default_factory=AuthPolicy)
    limits: TenantLimits = Field(default_factory=TenantLimits)
    channels: List[str] = Field(default_factory=lambda: ["chat"])
    tools: ToolFlags = Field(default_factory=ToolFlags)
    versions: ContractVersions = Field(default_factory=ContractVersions)
    legacy_config: Optional[str] = None


def _safe_tenant_id(tenant_id: str) -> str:
    tid = (tenant_id or "").strip()
    if not _TENANT_ID_RE.match(tid):
        raise ValueError(f"Invalid tenant id: {tenant_id!r}")
    return tid


def tenants_root() -> Path:
    return _REPO_ROOT / "tenants"


def platform_tenant_yaml_path(tenant_id: str) -> Path:
    return tenants_root() / _safe_tenant_id(tenant_id) / "tenant.yaml"


def _read_yaml_mapping(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML at {path} must be a mapping")
    return loaded


def load_platform_tenant(tenant_id: str) -> PlatformTenant:
    """Load ``tenants/{id}/tenant.yaml``. Missing file → default contract."""
    tid = _safe_tenant_id(tenant_id)
    path = platform_tenant_yaml_path(tid)
    if not path.is_file():
        return PlatformTenant(id=tid)

    data = _read_yaml_mapping(path)
    file_id = data.get("id")
    if file_id is not None and str(file_id).strip() != tid:
        raise ValueError(
            f"tenant.yaml id {file_id!r} does not match folder {tid!r} ({path})"
        )
    data["id"] = tid
    return PlatformTenant(**data)


def load_policy_yaml(tenant_id: str, name: str) -> Dict[str, Any]:
    """Load ``tenants/{id}/policies/{name}.yaml``. Missing or empty → ``{}``."""
    tid = _safe_tenant_id(tenant_id)
    policy_name = (name or "").strip()
    if not _POLICY_NAME_RE.match(policy_name):
        raise ValueError(f"Invalid policy name: {name!r}")

    path = tenants_root() / tid / "policies" / f"{policy_name}.yaml"
    if not path.is_file():
        return {}
    return _read_yaml_mapping(path)
