"""Durable jobs. Creation can share the business transaction; retries cannot redo it."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from db.models import OutboxRow
from db.session import SessionLocal


def enqueue(db, *, tenant_id: str, key: str, kind: str, payload: dict) -> None:
    if db.execute(select(OutboxRow.id).where(OutboxRow.dedup_key == key)).scalar_one_or_none():
        return
    # A nested transaction contains a simultaneous unique-key race.
    try:
        with db.begin_nested():
            db.add(OutboxRow(id=uuid.uuid4().hex, tenant_id=tenant_id, dedup_key=key,
                             kind=kind, payload_json=payload))
            db.flush()
    except IntegrityError:
        pass


def drain(tenant_id: str, limit: int = 20) -> int:
    from workflows.lease import ExecutionLease
    from controlplane.tenant_context import use_tenant
    completed = 0
    with use_tenant(tenant_id):
        with SessionLocal() as db:
            ids = list(db.execute(select(OutboxRow.id).where(OutboxRow.tenant_id == tenant_id,
                OutboxRow.status == "pending", OutboxRow.available_at <= datetime.utcnow())
                .order_by(OutboxRow.created_at).limit(limit)).scalars())
        for job_id in ids:
            with ExecutionLease("job:" + job_id, SessionLocal) as lease:
                if not lease.acquired:
                    continue
                with SessionLocal() as db:
                    job = db.get(OutboxRow, job_id)
                    if job is None or job.status != "pending":
                        continue
                    kind, payload = job.kind, dict(job.payload_json)
                failure = None
                try:
                    if kind == "workflow.resume":
                        from workflows.engine import WorkflowEngine
                        result = WorkflowEngine().resume(payload["run_id"])
                        if result.status in {"running", "retrying", "pending"}:
                            raise RuntimeError("workflow remains in flight")
                    elif kind == "webhook":
                        from controlplane.webhooks import send_delivery
                        send_delivery(payload, tenant_id=tenant_id, event_id=job_id)
                    elif kind == "workflow.cancel":
                        from workflows.approvals import _cancel_run
                        _cancel_run(SessionLocal, payload["run_id"], payload["case_id"])
                    elif kind == "email":
                        from controlplane.mail import send_email
                        send_email(**payload)
                    else:
                        raise ValueError("unknown job kind")
                except Exception as exc:
                    failure = type(exc).__name__  # no provider response/secrets in job errors
                lease.assert_owned()
                with SessionLocal() as db:
                    job = db.get(OutboxRow, job_id)
                    job.attempts += 1
                    job.last_error = failure
                    if failure:
                        job.status = "dead" if job.attempts >= 6 else "pending"
                        job.available_at = datetime.utcnow() + timedelta(seconds=min(3600, 2 ** job.attempts * 5))
                    else:
                        job.status = "delivered"
                        completed += 1
                    db.commit()
    return completed
