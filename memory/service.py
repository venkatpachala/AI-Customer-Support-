from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid

from sqlalchemy import select, desc

from memory.models import SessionMemory, CaseMemory
from db.session import SessionLocal
from db.models import (
    OPEN_CASE_STATUSES,
    CaseRow,
    MessageRow,
    PlatformConversationRow,
    SessionRow,
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _norm_order_id(order_id: Optional[str]) -> Optional[str]:
    if order_id is None:
        return None
    text = str(order_id).strip()
    return text or None


def find_open_case(
    tenant_id: str,
    customer_id: str,
    order_id: Optional[str] = None,
) -> Optional[CaseMemory]:
    """Latest open case for this tenant and customer.

    When ``order_id`` is set, the order must match. Cases are not shared
    across orders, and a resolved case is never returned. ``order_id`` of
    None returns the latest open case for the customer on any order; the
    reuse path does not call it that way.
    """
    return MemoryService().find_open_case(tenant_id, customer_id, order_id)


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
            "auth_level": row.auth_level or "anonymous",
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
            case.auth_level = row.auth_level or "anonymous"
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

            # attach active case if available.
            # A cross-session bind lives on platform_conversations because
            # sessions has no active_case_id column. Fall back to the case
            # that was opened on this session.
            session = self._session_from_row(row, messages=messages)
            linked = self._open_case_linked_to_session(db, row)
            if linked is not None:
                session.active_case_id = linked.case_id
                return session

            case_stmt = (
                select(CaseRow)
                .where(CaseRow.session_id == session_id)
                .where(CaseRow.tenant_id == row.tenant_id)
                .where(CaseRow.customer_id == row.customer_id)
                .where(CaseRow.status.in_(OPEN_CASE_STATUSES))
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
        # The widget cookie is not a memory session id. Continue the customer's open journey.
        latest = self._latest_session_for_customer(customer_id, tenant_id)
        if latest is not None:
            return latest
        return self.create_session(customer_id=customer_id, tenant_id=tenant_id)

    def _latest_session_for_customer(self, customer_id: str, tenant_id: str) -> Optional[SessionMemory]:
        with SessionLocal() as db:
            row = db.execute(
                select(SessionRow)
                .where(SessionRow.customer_id == customer_id)
                .where(SessionRow.tenant_id == tenant_id)
                .order_by(desc(SessionRow.updated_at))
                .limit(1)
            ).scalars().first()
            return self._session_from_row(row) if row else None

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
            row.auth_level = getattr(case, "auth_level", None) or row.auth_level or "anonymous"
            row.escalated = (case.status == "escalated") or bool(getattr(case, "escalated", False))
            row.updated_at = datetime.utcnow()
            db.commit()

    def find_open_case(
        self,
        tenant_id: str,
        customer_id: str,
        order_id: Optional[str] = None,
    ) -> Optional[CaseMemory]:
        """Latest still-open case for this tenant + customer.

        Pass ``order_id`` to require that order. Without it, this is a
        customer-wide lookup and must not be used to merge two orders.
        """
        order_id = _norm_order_id(order_id)
        with SessionLocal() as db:
            stmt = (
                select(CaseRow)
                .where(CaseRow.tenant_id == tenant_id)
                .where(CaseRow.customer_id == customer_id)
                .where(CaseRow.status.in_(OPEN_CASE_STATUSES))
            )
            if order_id is not None:
                stmt = stmt.where(CaseRow.order_id == order_id)
            stmt = stmt.order_by(desc(CaseRow.updated_at)).limit(1)
            row = db.execute(stmt).scalars().first()
            return self._case_from_row(row) if row else None

    def get_or_create_case(
        self,
        session: SessionMemory,
        order_id: Optional[str] = None,
        issue_type: Optional[str] = None,
        channel: str = "chat",
    ) -> CaseMemory:
        """Reuse one open journey for tenant + customer + order.

        Order of lookup:

        1. ``session.active_case_id`` when that case is still open, and the
           caller passed no order, the case has no order yet, or the order
           matches. A different order is not reused.
        2. Any session's open case with the same tenant, customer, and order.
        3. The latest open case opened on this session, same order rule.
        4. A new case.

        An empty case order is filled in when the caller supplies one.
        ``issue_type`` is written only alongside that fill, and only when
        the case does not already have one. The case row keeps the session
        that opened it; this session is linked through platform_conversations.
        """
        order_id = _norm_order_id(order_id)
        issue_type = (issue_type or "").strip() or None

        active_id = getattr(session, "active_case_id", None)
        if active_id:
            active = self.get_case(active_id)
            if self._case_reusable_for_order(active, session, order_id):
                self._attach_order_if_empty(active, order_id, issue_type)
                self._bind_session_to_case(session, active, channel=channel)
                return active

        if order_id:
            shared = self.find_open_case(session.tenant_id, session.customer_id, order_id)
            if shared is not None:
                self._attach_order_if_empty(shared, order_id, issue_type)
                self._bind_session_to_case(session, shared, channel=channel)
                return shared

        on_session = self._latest_open_case_on_session(session.session_id)
        if on_session is not None and self._case_reusable_for_order(on_session, session, order_id):
            self._attach_order_if_empty(on_session, order_id, issue_type)
            self._bind_session_to_case(session, on_session, channel=channel)
            return on_session

        created = self.create_case(
            session_id=session.session_id,
            customer_id=session.customer_id,
            tenant_id=session.tenant_id,
            order_id=order_id,
            issue_type=issue_type,
        )
        self._bind_session_to_case(session, created, channel=channel)
        return created

    def get_or_create_active_case(
        self,
        session: SessionMemory,
        order_id: Optional[str] = None,
        issue_type: Optional[str] = None,
        customer_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        channel: str = "chat",
    ) -> CaseMemory:
        """Session entry used by chat and voice. Same reuse rules as ``get_or_create_case``.

        ``customer_id`` and ``tenant_id`` are accepted so older callers can
        pass them. The session row remains the source of those identities.
        """
        del customer_id, tenant_id
        return self.get_or_create_case(
            session,
            order_id=order_id,
            issue_type=issue_type,
            channel=channel,
        )

    def _case_reusable_for_order(
        self,
        case: Optional[CaseMemory],
        session: SessionMemory,
        order_id: Optional[str],
    ) -> bool:
        if case is None:
            return False
        if case.status not in OPEN_CASE_STATUSES:
            return False
        if case.tenant_id != session.tenant_id or case.customer_id != session.customer_id:
            return False
        case_order = _norm_order_id(case.order_id)
        if order_id is None or case_order is None or case_order == order_id:
            return True
        return False

    def _latest_open_case_on_session(self, session_id: str) -> Optional[CaseMemory]:
        with SessionLocal() as db:
            stmt = (
                select(CaseRow)
                .where(CaseRow.session_id == session_id)
                .where(CaseRow.status.in_(OPEN_CASE_STATUSES))
                .order_by(desc(CaseRow.updated_at))
                .limit(1)
            )
            row = db.execute(stmt).scalars().first()
            return self._case_from_row(row) if row else None

    def _attach_order_if_empty(
        self,
        case: CaseMemory,
        order_id: Optional[str],
        issue_type: Optional[str],
    ) -> None:
        if not order_id or _norm_order_id(case.order_id):
            return
        case.order_id = order_id
        if issue_type and not (case.issue_type or "").strip():
            case.issue_type = issue_type
        self.save_case(case)

    def _bind_session_to_case(
        self,
        session: SessionMemory,
        case: CaseMemory,
        channel: str = "chat",
    ) -> None:
        session.active_case_id = case.case_id
        self.save_session(session)
        channel_name = (channel or "chat").strip() or "chat"
        with SessionLocal() as db:
            existing = db.execute(
                select(PlatformConversationRow)
                .where(PlatformConversationRow.session_id == session.session_id)
                .where(PlatformConversationRow.case_id == case.case_id)
            ).scalars().first()
            if existing is not None:
                return
            db.add(
                PlatformConversationRow(
                    id=_new_id(),
                    tenant_id=session.tenant_id,
                    customer_id=session.customer_id,
                    session_id=session.session_id,
                    case_id=case.case_id,
                    channel=channel_name,
                )
            )
            db.commit()

    def _open_case_linked_to_session(self, db, session_row: SessionRow) -> Optional[CaseRow]:
        links = db.execute(
            select(PlatformConversationRow)
            .where(PlatformConversationRow.session_id == session_row.session_id)
            .order_by(desc(PlatformConversationRow.created_at))
        ).scalars().all()
        for link in links:
            if link.tenant_id != session_row.tenant_id or link.customer_id != session_row.customer_id:
                continue
            case_row = db.get(CaseRow, link.case_id)
            if case_row is None:
                continue
            if case_row.status not in OPEN_CASE_STATUSES:
                continue
            if case_row.tenant_id != session_row.tenant_id or case_row.customer_id != session_row.customer_id:
                continue
            return case_row
        return None

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