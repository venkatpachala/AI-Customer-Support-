"""New platform tables are created by the existing init_db() path."""
from sqlalchemy import inspect, text

from db.session import engine, init_db


def test_init_db_creates_workflow_and_platform_tables():
    init_db()
    expected = {"workflow_runs", "human_tasks", "platform_events"}

    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            names = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
    else:
        names = set(inspect(engine).get_table_names())

    missing = expected - names
    assert not missing, f"create_all did not create {sorted(missing)}"
