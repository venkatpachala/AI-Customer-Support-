"""Apply db/migrations once. A non-empty schema_migrations table means already applied."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from db.session import engine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_BOOT = "001_pilot"


def _statements(sql: str) -> list[str]:
    statements = []
    for chunk in sql.split(";"):
        lines = [
            line for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
    return statements


def apply_migrations() -> None:
    sql_path = MIGRATIONS / "001_pilot.sql"
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP)"
        ))
        count = conn.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar() or 0
        if int(count) == 0 and sql_path.is_file():
            for statement in _statements(sql_path.read_text(encoding="utf-8")):
                conn.execute(text(statement))
            conn.execute(
                text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"),
                {"version": _BOOT},
            )
    relax_interaction_text_columns()


def relax_interaction_text_columns() -> None:
    """create_all does not drop NOT NULL on an existing interactions table.

    The 90-day sweep sets message and response to NULL. Rebuild the SQLite
    table when those columns are still required. Postgres can drop the
    constraint in place. Workflow and approval tables are not touched.
    """
    from sqlalchemy import inspect

    if "interactions" not in set(inspect(engine).get_table_names()):
        return
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE interactions ALTER COLUMN message DROP NOT NULL"))
            conn.execute(text("ALTER TABLE interactions ALTER COLUMN response DROP NOT NULL"))
        return
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        info = list(conn.execute(text("PRAGMA table_info(interactions)")).mappings())
        locked = [
            row for row in info
            if row["name"] in {"message", "response"} and int(row["notnull"] or 0) == 1
        ]
        if not locked:
            return
        index_sql = [
            row[0]
            for row in conn.execute(text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'interactions' AND sql IS NOT NULL"
            )).all()
            if row[0]
        ]
        defs: list[str] = []
        names: list[str] = []
        for row in info:
            name = str(row["name"])
            names.append(name)
            quoted = '"' + name.replace('"', '""') + '"'
            parts = [quoted, str(row["type"] or "TEXT")]
            if int(row["pk"] or 0):
                parts.append("PRIMARY KEY")
            elif name not in {"message", "response"} and int(row["notnull"] or 0):
                parts.append("NOT NULL")
            if row["dflt_value"] is not None:
                parts.append(f"DEFAULT {row['dflt_value']}")
            defs.append(" ".join(parts))
        col_list = ", ".join('"' + name.replace('"', '""') + '"' for name in names)
        conn.exec_driver_sql(
            "CREATE TABLE interactions__text_nullable (" + ", ".join(defs) + ")"
        )
        conn.exec_driver_sql(
            f"INSERT INTO interactions__text_nullable ({col_list}) "
            f"SELECT {col_list} FROM interactions"
        )
        conn.exec_driver_sql("DROP TABLE interactions")
        conn.exec_driver_sql("ALTER TABLE interactions__text_nullable RENAME TO interactions")
        for statement in index_sql:
            conn.exec_driver_sql(statement)
