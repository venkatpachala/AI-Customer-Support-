"""Deletion queue. Purging a tenant does not call Stripe."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from controlplane.keys import ensure_tenant, set_killed
from db.models import (
    CaseRow,
    ConnectionRow,
    HumanTaskRow,
    IntakeRequestRow,
    KnowledgeSnapshotRow,
    MessageRow,
    PlatformEventRow,
    TenantAccountRow,
    WorkflowRunRow,
    WorkflowStepRow,
)
from db.session import SessionLocal

_ROOT = Path(__file__).resolve().parents[1]


def queue_purge(tenant_id: str, email: str, note: str, session_factory=SessionLocal) -> None:
    ensure_tenant(tenant_id, session_factory=session_factory)
    with session_factory() as db:
        row = db.get(TenantAccountRow, tenant_id)
        row.purge_requested_at = datetime.utcnow()
        row.killed_at = datetime.utcnow()
        db.add(
            IntakeRequestRow(
                id=str(uuid.uuid4()),
                kind="deletion",
                email=(email or "")[:256],
                tenant_id=tenant_id,
                note=(note or "")[:2000],
            )
        )
        db.add(
            PlatformEventRow(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type="deletion.queued",
                payload_json={"email": email},
            )
        )
        db.commit()


def run_purge(tenant_id: str, session_factory=SessionLocal) -> dict:
    """Remove documents, cases, and credentials for one tenant. No payment call."""
    ensure_tenant(tenant_id, session_factory=session_factory)
    set_killed(tenant_id, True, session_factory=session_factory)
    folder = _ROOT / "tenants" / tenant_id / "knowledge" / "uploads"
    removed_files = 0
    if folder.is_dir():
        for path in folder.glob("*.pdf"):
            path.unlink()
            removed_files += 1
    with session_factory() as db:
        documents = db.execute(
            delete(KnowledgeSnapshotRow).where(KnowledgeSnapshotRow.tenant_id == tenant_id)
        ).rowcount or 0
        credentials = db.execute(
            delete(ConnectionRow).where(ConnectionRow.tenant_id == tenant_id)
        ).rowcount or 0
        case_ids = [
            row[0]
            for row in db.execute(
                select(CaseRow.case_id).where(CaseRow.tenant_id == tenant_id)
            ).all()
        ]
        run_ids = [
            row[0]
            for row in db.execute(
                select(WorkflowRunRow.id).where(WorkflowRunRow.tenant_id == tenant_id)
            ).all()
        ]
        if run_ids:
            db.execute(delete(WorkflowStepRow).where(WorkflowStepRow.run_id.in_(run_ids)))
        db.execute(delete(HumanTaskRow).where(HumanTaskRow.tenant_id == tenant_id))
        db.execute(delete(WorkflowRunRow).where(WorkflowRunRow.tenant_id == tenant_id))
        if case_ids:
            db.execute(delete(MessageRow).where(MessageRow.case_id.in_(case_ids)))
        cases = db.execute(
            delete(CaseRow).where(CaseRow.tenant_id == tenant_id)
        ).rowcount or 0
        db.add(
            PlatformEventRow(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type="deletion.purged",
                payload_json={
                    "documents": int(documents),
                    "credentials": int(credentials),
                    "cases": int(cases),
                    "files": removed_files,
                },
            )
        )
        row = db.get(TenantAccountRow, tenant_id)
        if row is not None:
            row.purge_requested_at = row.purge_requested_at or datetime.utcnow()
            row.live_enabled_at = None
        db.commit()
    return {
        "tenant_id": tenant_id,
        "documents": int(documents),
        "credentials": int(credentials),
        "cases": int(cases),
        "files": removed_files,
    }


def purge_is_queued(tenant_id: str, session_factory=SessionLocal) -> bool:
    with session_factory() as db:
        row = db.get(TenantAccountRow, tenant_id)
        return bool(row and row.purge_requested_at)
