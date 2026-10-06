"""Print the Zepto test keys once.

    python -m controlplane.seed
"""
from __future__ import annotations

import os

from db.session import init_db
from controlplane.keys import ensure_tenant, issue_key, list_keys


def main() -> None:
    os.environ.setdefault("TOOLS_MODE", "mock")
    init_db()
    ensure_tenant("zepto", "Zepto")
    existing = list_keys("zepto")
    widget = next((row for row in existing if row["role"] == "widget" and row["mode"] == "test" and not row["revoked_at"]), None)
    supervisor = next((row for row in existing if row["role"] == "supervisor" and row["mode"] == "test" and not row["revoked_at"]), None)
    if widget and supervisor:
        print("zepto test keys already issued")
        print(f"widget prefix {widget['prefix']}")
        print(f"supervisor prefix {supervisor['prefix']}")
        return
    if widget is None:
        _row, widget_secret = issue_key("zepto", role="widget", mode="test")
        print("zepto test widget key (shown once)")
        print(widget_secret)
    if supervisor is None:
        _row, supervisor_secret = issue_key("zepto", role="supervisor", mode="test")
        print("zepto test supervisor key (shown once)")
        print(supervisor_secret)
    print("owner login ops@zepto.local uses OPS_PASSWORD")


if __name__ == "__main__":
    main()
