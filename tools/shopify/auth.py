import os
import re
from datetime import date


def shopify_api_version() -> str:
    from controlplane.settings import production
    value = os.getenv("SHOPIFY_API_VERSION", "").strip()
    if not value:
        if production():
            raise RuntimeError("SHOPIFY_API_VERSION must be explicitly configured")
        value = "2026-07"
    if not re.fullmatch(r"20\d{2}-(01|04|07|10)", value):
        raise RuntimeError("SHOPIFY_API_VERSION must be a stable quarterly version")
    released = date(int(value[:4]), int(value[5:]), 1)
    age = (date.today() - released).days
    if production() and not 0 <= age < 365:
        raise RuntimeError("SHOPIFY_API_VERSION must be a currently supported version")
    return value


def canonical_shop_domain(domain: str) -> str:
    value = domain.removeprefix("https://").rstrip("/").lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", value):
        raise RuntimeError("Shopify requires a canonical myshopify.com domain")
    return value

def get_shopify_auth():
    token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    shop = os.getenv("SHOPIFY_SHOP_URL")
    mode = os.getenv("TOOLS_MODE", "mock").lower()

    if mode == "mock":
        return {
            "access_token": token or "mock-token",
            "shop_url": shop or "mock.myshopify.com",
            "api_version": shopify_api_version(),
            "mock": True,
        }

    if not token:
        raise RuntimeError("SHOPIFY_ACCESS_TOKEN is not set")
    if not shop:
        raise RuntimeError("SHOPIFY_SHOP_URL is not set")

    return {
        "access_token": token,
        "shop_url": shop,
        "api_version": shopify_api_version(),
        "mock": False,
    }

def get_shopify_base_url() -> str:
    domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip().rstrip("/")
    version = shopify_api_version()

    if not domain:
        raise RuntimeError("SHOPIFY_SHOP_DOMAIN is not set")

    domain = canonical_shop_domain(domain)
    return f"https://{domain}/admin/api/{version}"
