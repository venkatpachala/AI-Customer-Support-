import os
import yaml
from config.schema import TenantConfig
from config.tenant_contract import load_platform_tenant, platform_tenant_yaml_path


def load_tenant_config(tenant_id: str) -> TenantConfig:
    """Legacy brand config. Platform refund cap overlays the HITL threshold."""
    path = os.path.join("config", "tenants", tenant_id, "config.yaml")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Tenant config not found for '{tenant_id}' at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cfg = TenantConfig(**data)
    return _overlay_platform_refund_cap(tenant_id, cfg)


def _overlay_platform_refund_cap(tenant_id: str, cfg: TenantConfig) -> TenantConfig:
    """Keep HITL aligned with the platform contract when that file exists.

    Only ``approval.high_value_refund_limit`` is overwritten, from
    ``limits.auto_refund_max``. Every other legacy field stays as authored.
    A missing platform file leaves the legacy config untouched.
    """
    if not platform_tenant_yaml_path(tenant_id).is_file():
        return cfg
    platform = load_platform_tenant(tenant_id)
    cfg.approval.high_value_refund_limit = float(platform.limits.auto_refund_max)
    return cfg