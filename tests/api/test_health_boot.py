"""Mock boot: /health does not need Shopify or Stripe secrets."""
import os

os.environ["TOOLS_MODE"] = "mock"
os.environ.pop("SHOPIFY_SHOP_DOMAIN", None)
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("GMAIL_CLIENT_ID", None)
os.environ.pop("GMAIL_CLIENT_SECRET", None)
os.environ.pop("GMAIL_REFRESH_TOKEN", None)

from fastapi.testclient import TestClient
from gateway.main import app

client = TestClient(app)


def test_health_reports_mock_mode_and_db():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tools_mode"] == "mock"
    assert body["db"] == "ok"
