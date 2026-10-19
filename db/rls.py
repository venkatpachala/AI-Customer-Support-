"""Postgres row-level safety net. SQLite keeps the application filter only.

Policies hide every row unless the session set app.tenant_id. The application
sets that value from the key or cookie, not from the JSON body. Lookup tables
used before the tenant is known (api_keys, owner_accounts) stay out of RLS.
"""
from __future__ import annotations

from sqlalchemy import text

from db.session import engine

_TABLES = (
    "cases",
    "interactions",
    "knowledge_snapshots",
    "tenant_connections",
    "workflow_runs",
    "human_tasks",
    "tool_calls",
    "evidence",
    "platform_events",
    "daily_usage",
    "knowledge_contents",
    "operator_cases",
    "delivery_outbox",
    "verification_challenges",
    "evidence_files",
    "customer_sessions",
    "sessions",
    "platform_conversations",
    "platform_customers",
    "platform_tenants",
    "chat_receipts",
    "order_payments",
    "refund_budgets",
    "refund_reservations",
)


def apply_tenant_rls() -> None:
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import inspect

    present = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table in _TABLES:
            if table not in present:
                continue
            policy = f"d2c_tenant_{table}"
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            auth_lookup = (" OR id = current_setting('app.customer_session_id', true)"
                           if table == "customer_sessions" else "")
            conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
            conn.execute(text(
                f"""
                DO $$
                BEGIN
                    CREATE POLICY {policy} ON {table}
                    USING (
                        (current_setting('app.tenant_id', true) <> ''
                        AND tenant_id = current_setting('app.tenant_id', true))
                        {auth_lookup}
                    )
                    WITH CHECK (
                        tenant_id = current_setting('app.tenant_id', true)
                    );
                EXCEPTION
                    WHEN duplicate_object THEN NULL;
                END $$;
                """
            ))
        # Child tables inherit the tenant boundary through their parent row.
        for table, parent, local_key, parent_key in (
            ("messages", "sessions", "session_id", "session_id"),
            ("workflow_steps", "workflow_runs", "run_id", "id"),
        ):
            if table not in present:
                continue
            predicate = f"EXISTS (SELECT 1 FROM {parent} p WHERE p.{parent_key} = {table}.{local_key} AND p.tenant_id = current_setting('app.tenant_id', true))"
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            conn.execute(text(f"""DO $$ BEGIN
                CREATE POLICY d2c_tenant_{table} ON {table}
                USING ({predicate}) WITH CHECK ({predicate});
                EXCEPTION WHEN duplicate_object THEN NULL; END $$;"""))
