import os

def get_shopify_auth():
    token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    shop = os.getenv("SHOPIFY_SHOP_URL")
    mode = os.getenv("TOOLS_MODE", "mock").lower()

    if mode == "mock":
        return {
            "access_token": token or "mock-token",
            "shop_url": shop or "mock.myshopify.com",
            "api_version": os.getenv("SHOPIFY_API_VERSION", "2024-10"),
            "mock": True,
        }

    if not token:
        raise RuntimeError("SHOPIFY_ACCESS_TOKEN is not set")
    if not shop:
        raise RuntimeError("SHOPIFY_SHOP_URL is not set")

    return {
        "access_token": token,
        "shop_url": shop,
        "api_version": os.getenv("SHOPIFY_API_VERSION", "2024-10"),
        "mock": False,
    }

def get_shopify_base_url() -> str:
    domain = os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip().rstrip("/")
    version = os.getenv("SHOPIFY_API_VERSION", "2024-10").strip()

    if not domain:
        raise RuntimeError("SHOPIFY_SHOP_DOMAIN is not set")

    # allow either raw domain or full URL
    if domain.startswith("http://") or domain.startswith("https://"):
        domain = domain.split("://", 1)[1]

    return f"https://{domain}/admin/api/{version}"
