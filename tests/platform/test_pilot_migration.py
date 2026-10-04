"""Pilot SQL runs once. SQLite stays the default for the gate."""
from db.migrate import apply_migrations
from db.session import SessionLocal, init_db
from sqlalchemy import text


def test_pilot_migration_applies_once():
    init_db()
    apply_migrations()
    with SessionLocal() as db:
        versions = list(db.execute(text("SELECT version FROM schema_migrations")).scalars())
        db.execute(text("SELECT 1 FROM customer_sessions"))
    assert versions.count("001_pilot") == 1
