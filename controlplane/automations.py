"""Persistent per-tenant capabilities, enforced by execution."""
from sqlalchemy import select
from db.models import PlatformTenantRow
from db.session import SessionLocal

def automation_enabled(tenant: str, action: str) -> bool:
    from controlplane.settings import production
    if production() and action == "cancel":
        return False  # No live cancellation adapter is implemented.
    with SessionLocal() as db:
        row = db.get(PlatformTenantRow, tenant)
        configured = (row.config_json or {}).get("automations", {}) if row else {}
    if action in configured:
        return bool(configured[action])
    from config.tenant_contract import platform_tenant_yaml_path
    from controlplane.keys import tenant_record
    from controlplane.settings import legacy_headers_allowed
    return action == "policy" or platform_tenant_yaml_path(tenant).is_file() or (legacy_headers_allowed() and tenant_record(tenant) is None)
