"""Platform tenant contract loader and the legacy brand overlay."""
from config.loaders import load_tenant_config
from config.schema import TenantConfig
from config.tenant_contract import load_platform_tenant, load_policy_yaml


def test_zepto_platform_contract_loads():
    tenant = load_platform_tenant("zepto")
    assert tenant.id == "zepto"
    assert tenant.brand == "Zepto"
    assert tenant.locale == "en-IN"
    assert tenant.currency == "INR"
    assert tenant.limits.auto_refund_max == 2000
    assert tenant.limits.manager_refund_max == 10000
    assert tenant.limits.photo_required_for == ["damaged", "missing_item"]
    assert tenant.auth.intents["policy"] == "anonymous"
    assert tenant.auth.intents["order_status"] == "identified"
    assert tenant.auth.intents["refund"] == "verified"
    assert tenant.auth.intents["return"] == "identified"
    assert tenant.auth.intents["cancel"] == "identified"
    assert tenant.channels == ["chat", "voice"]
    assert tenant.tools.shopify is True
    assert tenant.tools.stripe is True
    assert tenant.tools.gmail is True
    assert tenant.versions.agent
    assert tenant.versions.policy_pack
    assert tenant.versions.knowledge_snapshot
    assert tenant.legacy_config == "config/tenants/zepto/config.yaml"


def test_missing_tenant_does_not_raise():
    tenant = load_platform_tenant("no-such-brand")
    assert tenant.id == "no-such-brand"
    assert tenant.limits.auto_refund_max == 2000


def test_missing_policy_is_empty_and_zepto_stub_loads():
    assert load_policy_yaml("zepto", "does-not-exist") == {}
    refund = load_policy_yaml("zepto", "refund")
    assert refund["id"] == "refund"
    assert refund["thresholds"]["auto_refund_max"] == 2000


def test_legacy_loader_still_returns_zepto_brand():
    cfg = load_tenant_config("zepto")
    assert isinstance(cfg, TenantConfig)
    assert cfg.tenant_id == "zepto"
    assert cfg.brand.brand_name == "Zepto"
    assert cfg.approval.high_value_refund_limit == 2000
    assert cfg.approval.refund_auto_approve_limit == 500
    assert cfg.policy_namespace == "zepto"
    assert cfg.active is True
