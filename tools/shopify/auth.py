import os
from tools.base.auth import ApiKeyAuth


def get_shopify_auth() -> ApiKeyAuth:
    token = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SHOPIFY_ACCESS_TOKEN is not set")
    return ApiKeyAuth(header_name="X-Shopify-Access-Token", api_key=token)


def get_shopify_base_url() -> str:
    domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip().rstrip("/")
    version = os.getenv("SHOPIFY_API_VERSION", "2024-10").strip()

    if not domain:
        raise RuntimeError("SHOPIFY_SHOP_DOMAIN is not set")

    # allow either raw domain or full URL
    if domain.startswith("http://") or domain.startswith("https://"):
        domain = domain.split("://", 1)[1]

    return f"https://{domain}/admin/api/{version}"