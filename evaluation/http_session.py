"""Golden evaluations use real customer sessions instead of forged auth fields."""
import os
import uuid
from pathlib import Path
import requests


def open_evaluation_session(customer: str, tenant: str):
    key = os.getenv("EVAL_WIDGET_KEY", "")
    path = Path("artifacts/eval-widget-key")
    if not key and path.is_file():
        key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("EVAL_WIDGET_KEY is required for HTTP evaluations")
    origin = os.getenv("EVAL_API_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
    http = requests.Session()
    result = http.post(origin + "/v1/sessions", headers={"Authorization": "Bearer " + key},
        json={"customer_ref": customer, "tenant_id": tenant}, timeout=15)
    result.raise_for_status()
    token = result.json()["session_id"]
    http.headers["Authorization"] = "Session " + token
    return http, origin


def bootstrap():
    # Only an isolated, local mock server may use the auto-created fixture key.
    from db.session import init_db
    from controlplane.keys import ensure_tenant, issue_key
    if os.getenv("TOOLS_MODE", "mock") != "mock":
        raise RuntimeError("automatic evaluation key bootstrap is mock-only")
    init_db()
    ensure_tenant("zepto")
    _, key = issue_key("zepto", role="widget", mode="test")
    path = Path("artifacts/eval-widget-key")
    path.parent.mkdir(exist_ok=True)
    path.write_text(key, encoding="utf-8")
    print("Created isolated evaluation credential (not printed)")


if __name__ == "__main__":
    bootstrap()
