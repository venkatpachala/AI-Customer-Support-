import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc

from db.session import SessionLocal
from db.models import SessionRow, CaseRow, MessageRow


def _new_id() -> str:
    return str(uuid.uuid4())


class SessionObj:
    def __init__(self, row: SessionRow):
        self.session_id = row.session_id
        self.tenant_id = row.tenant_id
        self.customer_id = row.customer_id
        self.status = row.status


class CaseObj:
    def __init__(self, row: CaseRow):
        self.case_id = row.case_id
        self.session_id = row.session_id
        self.tenant_id = row.tenant_id
        self.customer_id = row.customer_id
        self.status = row.status or "open"
        self.issue_type = row.issue_type
        self.order_id = row.order_id
        self.missing_inputs = list(row.missing_inputs or [])
        self.photos_requested = bool(row.photos_requested)
        self.photos_received = bool(row.photos_received)
        self.escalated = bool(row.escalated)
        self.escalation_reason = row.escalation_reason
        self.tools_executed = list(row.tools_executed or [])
        self.tool_results_summary = dict(row.tool_results_summary or {})
        self.policy_citations = list(row.policy_citations or [])
        self.auth_level = row.auth_level or "anonymous"
        self.last_agent_action = row.last_agent_action


class MemoryDBStore:
    def get_or_create_session(
        self,
        customer_id: str,
        tenant_id: str,
        session_id: Optional[str] = None,
    ) -> SessionObj:
        with SessionLocal() as db:
            row = None
            if session_id:
                row = db.get(SessionRow, session_id)

            if row is None:
                row = SessionRow(
                    session_id=session_id or _new_id(),
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    status="active",
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            return SessionObj(row)

    def get_or_create_active_case(self, session: SessionObj) -> CaseObj:
        with SessionLocal() as db:
            stmt = (
                select(CaseRow)
                .where(CaseRow.session_id == session.session_id)
                .where(CaseRow.status.in_(["open", "waiting_customer", "escalated"]))
                .order_by(desc(CaseRow.updated_at))
                .limit(1)
            )
            row = db.execute(stmt).scalars().first()
            if row is None:
                row = CaseRow(
                    case_id=_new_id(),
                    session_id=session.session_id,
                    tenant_id=session.tenant_id,
                    customer_id=session.customer_id,
                    status="open",
                    missing_inputs=[],
                    tools_executed=[],
                    tool_results_summary={},
                    policy_citations=[],
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            return CaseObj(row)

    def append_message(
        self,
        session: SessionObj,
        role: str,
        content: str,
        case_id: Optional[str] = None,
    ) -> None:
        with SessionLocal() as db:
            db.add(
                MessageRow(
                    session_id=session.session_id,
                    case_id=case_id,
                    role=role,
                    content=content or "",
                )
            )
            # touch session updated_at
            srow = db.get(SessionRow, session.session_id)
            if srow:
                srow.updated_at = datetime.utcnow()
            db.commit()

    def update_case_from_result(self, case: CaseObj, **kwargs) -> CaseObj:
        with SessionLocal() as db:
            row = db.get(CaseRow, case.case_id)
            if row is None:
                return case

            field_map = [
                "status", "issue_type", "order_id", "missing_inputs",
                "photos_requested", "photos_received", "escalated",
                "escalation_reason", "tools_executed", "tool_results_summary",
                "policy_citations", "auth_level", "last_agent_action",
            ]
            for key in field_map:
                if key in kwargs and kwargs[key] is not None:
                    setattr(row, key, kwargs[key])

            # convenience: if escalated True, keep reason/status coherent
            if kwargs.get("escalated") is True and not row.status:
                row.status = "escalated"
            if kwargs.get("status"):
                row.status = kwargs["status"]

            row.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(row)
            return CaseObj(row)

    def to_state_context(self, session: SessionObj, case: CaseObj) -> Dict[str, Any]:
        with SessionLocal() as db:
            stmt = (
                select(MessageRow)
                .where(MessageRow.session_id == session.session_id)
                .order_by(MessageRow.id.desc())
                .limit(12)
            )
            rows = list(reversed(db.execute(stmt).scalars().all()))
            recent = [{"role": r.role, "content": r.content} for r in rows]

        return {
            "session_id": session.session_id,
            "case_id": case.case_id,
            "active_order_id": case.order_id,
            "missing_inputs": list(case.missing_inputs or []),
            "photos_requested": bool(case.photos_requested),
            "photos_received": bool(case.photos_received),
            "case_status": case.status,
            "auth_level": case.auth_level or "anonymous",
            "recent_messages": recent,
            "issue_type": case.issue_type,
            "escalation_reason": case.escalation_reason,
        }