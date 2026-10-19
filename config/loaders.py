import os
import yaml
from config.schema import TenantConfig
from config.tenant_contract import load_platform_tenant, platform_tenant_yaml_path


def load_tenant_config(tenant_id: str) -> TenantConfig:
    """Legacy brand config. Platform refund cap overlays the HITL threshold."""
    path = os.path.join("config", "tenants", tenant_id, "config.yaml")

    if not os.path.exists(path):
        from controlplane.keys import tenant_record
        from config.schema import BrandConfig, ApprovalThresholds, ToolEndpoints, EscalationConfig

        row = tenant_record(tenant_id)
        if row is None:
            raise FileNotFoundError(f"Unknown tenant '{tenant_id}'")
        platform = load_platform_tenant(tenant_id)
        from db.models import PlatformTenantRow
        from db.session import SessionLocal
        with SessionLocal() as db:
            stored = db.get(PlatformTenantRow, tenant_id)
            settings = (stored.config_json or {}).get("brand_settings", {}) if stored else {}
        return TenantConfig(
            tenant_id=tenant_id,
            brand=BrandConfig(brand_name=row.name or tenant_id, support_email=settings.get("support_email", ""), tone=platform.tone or "professional, polite, concise"),
            approval=ApprovalThresholds(refund_auto_approve_limit=platform.limits.auto_refund_max, high_value_refund_limit=platform.limits.auto_refund_max),
            tools=ToolEndpoints(), escalation=EscalationConfig(), policy_namespace=tenant_id,
            active=row.killed_at is None,
        )

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
