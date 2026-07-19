import os
import yaml
from config.schema import TenantConfig

def load_tenant_config(tenant_id: str) -> TenantConfig:
    path = os.path.join("config", "tenants", tenant_id, "config.yaml")

    if not os.path.exists(path):
        raise FileNotFoundError(f"Tenant config not found for '{tenant_id}' at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return TenantConfig(**data)