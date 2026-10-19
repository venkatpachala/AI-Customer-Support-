"""Run with python -m controlplane.worker. No elevated database role required."""
import argparse
import time
from datetime import datetime
from threading import Event, Thread
import uuid
from sqlalchemy import select
from controlplane.settings import validate_environment
from controlplane.outbox import drain
from db.models import TenantAccountRow, WorkerHeartbeatRow, RateLimitBucketRow
from db.session import SessionLocal, ensure_schema


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    validate_environment()
    ensure_schema()
    from tools.bootstrap import register_default_tools
    register_default_tools()
    instance = uuid.uuid4().hex
    def heartbeat():
        while True:
            with SessionLocal() as db:
                row = db.get(WorkerHeartbeatRow, instance)
                if row is None:
                    db.add(WorkerHeartbeatRow(id=instance))
                else:
                    row.updated_at = datetime.utcnow()
                db.commit()
            time.sleep(10)
    Thread(target=heartbeat, daemon=True).start()
    while True:
        with SessionLocal() as db:
            from sqlalchemy import delete
            db.execute(delete(RateLimitBucketRow).where(RateLimitBucketRow.expires_at < datetime.utcnow()))
            db.commit()
            tenants = list(db.execute(select(TenantAccountRow.id)).scalars())
        for tenant in tenants:
            drain(tenant)
        if args.once:
            return
        time.sleep(2)


if __name__ == "__main__":
    main()
