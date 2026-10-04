"""Mock mode constructs tool clients without live secrets."""
import os

import pytest

os.environ["TOOLS_MODE"] = "mock"
os.environ.pop("SHOPIFY_SHOP_DOMAIN", None)
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("GMAIL_CLIENT_ID", None)


def test_mock_clients_do_not_require_secrets(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "mock")
    monkeypatch.delenv("SHOPIFY_SHOP_DOMAIN", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    from tools.gmail.auth import GmailOAuth2Auth
    from tools.shopify.client import ShopifyClient
    from tools.stripe.client import StripeClient

    shopify = ShopifyClient()
    stripe = StripeClient()
    gmail = GmailOAuth2Auth()
    assert shopify.base_url.startswith("https://mock.")
    assert stripe.base_url
    assert gmail.mock is True


def test_live_shopify_still_requires_domain(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "live")
    monkeypatch.delenv("SHOPIFY_SHOP_DOMAIN", raising=False)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("SHOPIFY_SHOP_URL", "example.myshopify.com")
    from tools.shopify.client import ShopifyClient

    with pytest.raises(RuntimeError):
        ShopifyClient()
