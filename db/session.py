import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


DEFAULT_SQLITE_URL = "sqlite:///./data/d2c_agent.db"


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


class Base(DeclarativeBase):
    pass


def _build_engine():
    url = get_database_url()

    # Ensure SQLite folder exists
    if url.startswith("sqlite:///./"):
        db_path = url.replace("sqlite:///./", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connect_args = {}
    if url.startswith("sqlite:"):
        connect_args = {"check_same_thread": False}

    return create_engine(
        url,
        future=True,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _bind_tenant_guc(session, transaction, connection) -> None:
    """Postgres RLS reads app.tenant_id. An empty value matches no rows."""
    if connection.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    from controlplane.tenant_context import current_scope

    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": current_scope().tenant_id or ""},
    )


from sqlalchemy import event
from sqlalchemy.orm import Session as _OrmSession

event.listen(_OrmSession, "after_begin", _bind_tenant_guc)


def init_db() -> None:
    """Create tables if they do not exist, then apply the pilot SQL once."""
    from db import models  # noqa: F401
    from db.migrate import apply_migrations

    Base.metadata.create_all(bind=engine)
    apply_migrations()
    print(f"[DB] Initialized {engine.dialect.name} database")


def ensure_schema() -> None:
    from controlplane.settings import production
    if not production():
        init_db()
        return
    from sqlalchemy import inspect, text
    required = {"cases", "delivery_outbox", "knowledge_contents", "execution_leases", "operator_cases", "verification_challenges", "evidence_files", "chat_receipts", "worker_heartbeats", "rate_limit_buckets", "order_payments", "refund_budgets", "refund_reservations"}
    if required - set(inspect(engine).get_table_names()):
        raise RuntimeError("database migrations are required before starting production")
    with engine.connect() as connection:
        flags = connection.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
    if flags[0] or flags[1]:
        raise RuntimeError("production database role must not bypass row-level security")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
