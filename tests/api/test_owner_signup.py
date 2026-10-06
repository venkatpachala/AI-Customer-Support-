"""Signup creates an isolated tenant. Passwords are hashed. Wrong password is 401."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from db.models import InteractionRow, OwnerAccountRow
from db.session import SessionLocal, init_db
from gateway.main import app

client = TestClient(app)
init_db()


def _signup(email: str, password: str = "correct-horse"):
    return client.post("/signup", data={"email": email, "password": password}, follow_redirects=False)


def test_signup_sets_owner_cookie_and_shows_keys_once():
    email = f"a-{uuid.uuid4().hex[:8]}@brand.test"
    created = _signup(email)
    assert created.status_code == 303
    assert created.headers["location"].endswith("/app/install")
    cookie = created.cookies.get("d2c_owner")
    assert cookie
    install = client.get("/app/install", cookies={"d2c_owner": cookie})
    assert install.status_code == 200
    assert "d2c_test_" in install.text
    assert "Shown once" in install.text
    secret = install.text.split('id="test-key">', 1)[1].split("</pre>", 1)[0].strip()
    assert len(secret) > len("d2c_test_") + 6
    again = client.get("/app/install", cookies={"d2c_owner": cookie})
    assert secret not in again.text
    with SessionLocal() as db:
        row = db.query(OwnerAccountRow).filter(OwnerAccountRow.email == email).one()
        assert row.password_hash.startswith("pbkdf2$")
        assert "correct-horse" not in row.password_hash
        assert "pbkdf2" not in install.text


def test_wrong_password_is_401():
    email = f"b-{uuid.uuid4().hex[:8]}@brand.test"
    assert _signup(email).status_code == 303
    denied = client.post("/login", data={"email": email, "password": "wrong-password"})
    assert denied.status_code == 401
    assert "d2c_owner" not in denied.cookies


def test_brand_b_inbox_does_not_contain_brand_a_case():
    email_a = f"c-{uuid.uuid4().hex[:8]}@brand.test"
    email_b = f"d-{uuid.uuid4().hex[:8]}@brand.test"
    created_a = _signup(email_a)
    created_b = _signup(email_b)
    with SessionLocal() as db:
        owner_a = db.query(OwnerAccountRow).filter(OwnerAccountRow.email == email_a).one()
        marker = "case-only-brand-a-" + uuid.uuid4().hex[:8]
        db.add(
            InteractionRow(
                interaction_id=uuid.uuid4().hex,
                conversation_id=uuid.uuid4().hex,
                case_id=marker,
                tenant_id=owner_a.tenant_id,
                customer_id="customer-a",
                channel="chat",
                message="brand A private case",
                response="kept inside brand A",
                intent="refund",
            )
        )
        db.commit()
    inbox = client.get("/app/inbox", cookies={"d2c_owner": created_b.cookies.get("d2c_owner")})
    assert inbox.status_code == 200
    assert marker not in inbox.text
    assert "brand A private case" not in inbox.text
    foreign = client.get(
        f"/app/cases/{marker}",
        cookies={"d2c_owner": created_b.cookies.get("d2c_owner")},
    )
    assert "Case not found" in foreign.text
    own = client.get(
        f"/app/cases/{marker}",
        cookies={"d2c_owner": created_a.cookies.get("d2c_owner")},
    )
    assert marker in own.text
