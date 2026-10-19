"""Dedicated CI database only. Exercises policies with a non-bypass application role."""
import os
import uuid
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError


def main():
    admin_url = os.environ["POSTGRES_TEST_ADMIN_URL"]
    if make_url(admin_url).database != "d2c_test":
        raise RuntimeError("PostgreSQL integration checks require the dedicated d2c_test database")
    os.environ["DATABASE_URL"] = admin_url
    from db.session import init_db, engine
    from db.models import SessionRow, CaseRow, MessageRow, CustomerSessionRow
    from controlplane.tenant_context import use_tenant
    init_db()
    with engine.begin() as conn:
        conn.execute(text("""DO $$ BEGIN
            CREATE ROLE d2c_test_app LOGIN PASSWORD 'integration-test-only' NOSUPERUSER NOBYPASSRLS;
            EXCEPTION WHEN duplicate_object THEN NULL; END $$;"""))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO d2c_test_app"))
        conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO d2c_test_app"))
        conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO d2c_test_app"))
    app_url = make_url(admin_url).set(username="d2c_test_app", password="integration-test-only")
    app_engine = create_engine(app_url, pool_size=1, max_overflow=0)
    factory = sessionmaker(app_engine)
    tenant_a, tenant_b, session_id, case_id = [uuid.uuid4().hex for _ in range(4)]
    with use_tenant(tenant_a), factory() as db:
        from datetime import datetime, timedelta
        auth_id = uuid.uuid4().hex
        db.add(CustomerSessionRow(id=auth_id, tenant_id=tenant_a, customer_ref="fixture",
                                 expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.add(SessionRow(session_id=session_id, tenant_id=tenant_a, customer_id="fixture"))
        db.flush()
        db.add(CaseRow(case_id=case_id, session_id=session_id, tenant_id=tenant_a, customer_id="fixture"))
        db.flush()
        db.add(MessageRow(session_id=session_id, case_id=case_id, role="user", content="private fixture"))
        db.commit()
    for tenant, visible in ((tenant_a, True), (tenant_b, False), ("", False), (tenant_a, True)):
        with use_tenant(tenant), factory() as db:
            assert bool(db.execute(select(CaseRow).where(CaseRow.case_id == case_id)).scalars().all()) == visible
            assert bool(db.execute(select(MessageRow).where(MessageRow.case_id == case_id)).scalars().all()) == visible
    with use_tenant(""), factory() as db:
        assert db.get(CustomerSessionRow, auth_id) is None
        db.execute(text("SELECT set_config('app.customer_session_id', :token, true)"), {"token": auth_id})
        assert db.get(CustomerSessionRow, auth_id) is not None
    with use_tenant(""), factory() as db:
        assert db.get(CustomerSessionRow, auth_id) is None
    with use_tenant(tenant_b), factory() as db:
        try:
            db.add(SessionRow(session_id=uuid.uuid4().hex, tenant_id=tenant_a, customer_id="forged"))
            db.commit()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("RLS accepted a cross-tenant insert")
    app_engine.dispose()
    print("PostgreSQL RLS PASS: case and message isolation, pooled-connection reset, forbidden insert")


if __name__ == "__main__":
    main()
