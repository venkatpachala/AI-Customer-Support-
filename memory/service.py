from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid

from sqlalchemy import select, desc

from memory.models import SessionMemory, CaseMemory
from db.session import SessionLocal
from db.models import SessionRow, CaseRow, MessageRow


def _new_id() -> str:
    return str(uuid.uuid4())


class MemoryService:
    """
    Durable memory service.
    Public API stays the same (SessionMemory / CaseMemory),
    storage is SQLite/Postgres via SQLAlchemy.
    """

    # ---------------- Session mapping ----------------
    def _session_from_row(self, row: SessionRow, messages: Optional[List[dict]] = None) -> SessionMemory:
        data = {
            "session_id": row.session_id,
            "customer_id": row.customer_id,
            "tenant_id": row.tenant_id,
            "status": row.status or "active",
            "messages": messages or [],
            "active_case_id": None,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        # SessionMemory may ignore unknown fields depending on model config
        try:
            return SessionMemory(**data)
        except TypeError:
            # fallback for stricter constructors
            session = SessionMemory(customer_id=row.customer_id, tenant_id=row.tenant_id)
            session.session_id = row.session_id
            session.messages = messages or []
            return session

    def _case_from_row(self, row: CaseRow) -> CaseMemory:
        data = {
            "case_id": row.case_id,
            "session_id": row.session_id,
            "customer_id": row.customer_id,
            "tenant_id": row.tenant_id,
            "status": row.status or "open",
            "issue_type": row.issue_type,
            "order_id": row.order_id,
            "missing_inputs": list(row.missing_inputs or []),
            "photos_requested": bool(row.photos_requested),
            "photos_received": bool(row.photos_received),
            "tools_executed": list(row.tools_executed or []),
            "tool_results_summary": dict(row.tool_results_summary or {}),
            "policy_citations": list(row.policy_citations or []),
            "escalation_reason": row.escalation_reason,
            "last_agent_action": row.last_agent_action,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        try:
            return CaseMemory(**data)
        except TypeError:
            case = CaseMemory(
                session_id=row.session_id,
                customer_id=row.customer_id,
                tenant_id=row.tenant_id,
                order_id=row.order_id,
                issue_type=row.issue_type,
            )
            case.case_id = row.case_id
            case.status = row.status or "open"
            case.missing_inputs = list(row.missing_inputs or [])
            case.photos_requested = bool(row.photos_requested)
            case.photos_received = bool(row.photos_received)
            case.tools_executed = list(row.tools_executed or [])
            case.tool_results_summary = dict(row.tool_results_summary or {})
            case.policy_citations = list(row.policy_citations or [])
            case.escalation_reason = row.escalation_reason
            case.last_agent_action = row.last_agent_action
            return case

    def _load_messages(self, db, session_id: str, limit: int = 20) -> List[dict]:
        stmt = (
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.id.desc())
            .limit(limit)
        )
        rows = list(reversed(db.execute(stmt).scalars().all()))
        return [
            {
                "role": r.role,
                "content": r.content,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    # ---------------- Session API ----------------
    def get_session(self, session_id: str) -> Optional[SessionMemory]:
        with SessionLocal() as db:
            row = db.get(SessionRow, session_id)
            if not row:
                return None
            messages = self._load_messages(db, session_id, limit=20)

            # attach active case if available
            session = self._session_from_row(row, messages=messages)
            case_stmt = (
                select(CaseRow)
                .where(CaseRow.session_id == session_id)
                .where(CaseRow.status.in_(["open", "waiting_customer", "escalated"]))
                .order_by(desc(CaseRow.updated_at))
                .limit(1)
            )
            case_row = db.execute(case_stmt).scalars().first()
            if case_row:
                session.active_case_id = case_row.case_id
            return session

    def create_session(self, customer_id: str, tenant_id: str, session_id: Optional[str] = None) -> SessionMemory:
        with SessionLocal() as db:
            row = SessionRow(
                session_id=session_id or _new_id(),
                customer_id=customer_id,
                tenant_id=tenant_id,
                status="active",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._session_from_row(row, messages=[])

    def get_or_create_session(
        self,
        customer_id: str,
        tenant_id: str,
        session_id: Optional[str] = None,
    ) -> SessionMemory:
        if session_id:
            existing = self.get_session(session_id)
            if existing:
                return existing
            return self.create_session(customer_id=customer_id, tenant_id=tenant_id, session_id=session_id)
        return self.create_session(customer_id=customer_id, tenant_id=tenant_id)

    def save_session(self, session: SessionMemory):
        with SessionLocal() as db:
            row = db.get(SessionRow, session.session_id)
            if not row:
                row = SessionRow(
                    session_id=session.session_id,
                    customer_id=session.customer_id,
                    tenant_id=session.tenant_id,
                    status=getattr(session, "status", "active") or "active",
                )
                db.add(row)
            else:
                row.customer_id = session.customer_id
                row.tenant_id = session.tenant_id
                row.status = getattr(session, "status", row.status) or row.status
                row.updated_at = datetime.utcnow()
            db.commit()

    # ---------------- Case API ----------------
    def get_case(self, case_id: str) -> Optional[CaseMemory]:
        with SessionLocal() as db:
            row = db.get(CaseRow, case_id)
            return self._case_from_row(row) if row else None

    def create_case(
        self,
        session_id: str,
        customer_id: str,
        tenant_id: str,
        order_id: Optional[str] = None,
        issue_type: Optional[str] = None,
    ) -> CaseMemory:
        with SessionLocal() as db:
            row = CaseRow(
                case_id=_new_id(),
                session_id=session_id,
                customer_id=customer_id,
                tenant_id=tenant_id,
                order_id=order_id,
                issue_type=issue_type,
                status="open",
                missing_inputs=[],
                tools_executed=[],
                tool_results_summary={},
                policy_citations=[],
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._case_from_row(row)

    def save_case(self, case: CaseMemory):
        with SessionLocal() as db:
            row = db.get(CaseRow, case.case_id)
            if not row:
                row = CaseRow(
                    case_id=case.case_id,
                    session_id=case.session_id,
                    customer_id=case.customer_id,
                    tenant_id=case.tenant_id,
                )
                db.add(row)

            row.status = case.status or row.status or "open"
            row.issue_type = case.issue_type
            row.order_id = case.order_id
            row.missing_inputs = list(case.missing_inputs or [])
            row.photos_requested = bool(case.photos_requested)
            row.photos_received = bool(case.photos_received)
            row.tools_executed = list(case.tools_executed or [])
            row.tool_results_summary = dict(case.tool_results_summary or {})
            row.policy_citations = list(getattr(case, "policy_citations", []) or [])
            row.escalation_reason = case.escalation_reason
            row.last_agent_action = getattr(case, "last_agent_action", None)
            row.escalated = (case.status == "escalated") or bool(getattr(case, "escalated", False))
            row.updated_at = datetime.utcnow()
            db.commit()

    def get_or_create_active_case(self, session: SessionMemory) -> CaseMemory:
        if getattr(session, "active_case_id", None):
            case = self.get_case(session.active_case_id)
            if case and case.status in ["open", "waiting_customer", "escalated"]:
                return case

        with SessionLocal() as db:
            stmt = (
                select(CaseRow)
                .where(CaseRow.session_id == session.session_id)
                .where(CaseRow.status.in_(["open", "waiting_customer", "escalated"]))
                .order_by(desc(CaseRow.updated_at))
                .limit(1)
            )
            row = db.execute(stmt).scalars().first()
            if row:
                case = self._case_from_row(row)
                session.active_case_id = case.case_id
                self.save_session(session)
                return case

        case = self.create_case(
            session_id=session.session_id,
            customer_id=session.customer_id,
            tenant_id=session.tenant_id,
        )
        session.active_case_id = case.case_id
        self.save_session(session)
        return case

    # ---------------- Helpers ----------------
    def append_message(self, session: SessionMemory, role: str, content: str):
        with SessionLocal() as db:
            db.add(
                MessageRow(
                    session_id=session.session_id,
                    case_id=getattr(session, "active_case_id", None),
                    role=role,
                    content=content or "",
                )
            )
            srow = db.get(SessionRow, session.session_id)
            if srow:
                srow.updated_at = datetime.utcnow()
            db.commit()

        # keep in-memory list compatible for current request
        if not hasattr(session, "messages") or session.messages is None:
            session.messages = []
        session.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        session.messages = session.messages[-20:]

    def to_state_context(self, session: SessionMemory, case: CaseMemory) -> Dict[str, Any]:
        # Prefer DB messages for durability across restarts
        with SessionLocal() as db:
            recent = self._load_messages(db, session.session_id, limit=6)

        if not recent:
            recent = list(getattr(session, "messages", []) or [])[-6:]

        return {
            "session_id": session.session_id,
            "case_id": case.case_id,
            "active_order_id": case.order_id,
            "issue_type": case.issue_type,
            "case_status": case.status,
            "missing_inputs": case.missing_inputs,
            "photos_requested": case.photos_requested,
            "photos_received": case.photos_received,
            "tools_executed": case.tools_executed,
            "tool_results_summary": case.tool_results_summary,
            "escalation_reason": case.escalation_reason,
            "recent_messages": recent,
            "auth_level": getattr(case, "auth_level", "anonymous"),
        }

    def update_case_from_result(
        self,
        case: CaseMemory,
        *,
        order_id: Optional[str] = None,
        issue_type: Optional[str] = None,
        missing_inputs: Optional[List[str]] = None,
        photos_requested: Optional[bool] = None,
        photos_received: Optional[bool] = None,
        tools_executed: Optional[List[str]] = None,
        tool_results_summary: Optional[Dict[str, Any]] = None,
        policy_citations: Optional[List[str]] = None,
        escalated: Optional[bool] = None,
        escalation_reason: Optional[str] = None,
        last_agent_action: Optional[str] = None,
        status: Optional[str] = None,
    ) -> CaseMemory:
        if order_id:
            case.order_id = order_id
        if issue_type:
            case.issue_type = issue_type
        if missing_inputs is not None:
            case.missing_inputs = missing_inputs
        if photos_requested is not None:
            case.photos_requested = photos_requested
        if photos_received is not None:
            case.photos_received = photos_received
        if tools_executed is not None:
            merged = list(case.tools_executed or [])
            for t in tools_executed:
                if t not in merged:
                    merged.append(t)
            case.tools_executed = merged
        if tool_results_summary is not None:
            current = dict(case.tool_results_summary or {})
            current.update(tool_results_summary)
            case.tool_results_summary = current
        if policy_citations is not None:
            case.policy_citations = policy_citations
        if escalated:
            case.status = "escalated"
            case.escalation_reason = escalation_reason
        if status:
            case.status = status
        if last_agent_action:
            case.last_agent_action = last_agent_action

        self.save_case(case)
        return case