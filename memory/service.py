import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from memory.models import SessionMemory, CaseMemory

DATA_DIR = Path("memory/data")
SESSIONS_FILE = DATA_DIR / "sessions.json"
CASES_FILE = DATA_DIR / "cases.json"


class MemoryService:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not SESSIONS_FILE.exists():
            SESSIONS_FILE.write_text("{}", encoding="utf-8")
        if not CASES_FILE.exists():
            CASES_FILE.write_text("{}", encoding="utf-8")

    # ---------------- Internal IO ----------------
    def _load_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_json(self, path: Path, data: dict):
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ---------------- Session ----------------
    def get_session(self, session_id: str) -> Optional[SessionMemory]:
        data = self._load_json(SESSIONS_FILE)
        raw = data.get(session_id)
        return SessionMemory(**raw) if raw else None

    def create_session(self, customer_id: str, tenant_id: str) -> SessionMemory:
        session = SessionMemory(customer_id=customer_id, tenant_id=tenant_id)
        data = self._load_json(SESSIONS_FILE)
        data[session.session_id] = session.dict()
        self._save_json(SESSIONS_FILE, data)
        return session

    def get_or_create_session(
        self,
        customer_id: str,
        tenant_id: str,
        session_id: Optional[str] = None
    ) -> SessionMemory:
        if session_id:
            existing = self.get_session(session_id)
            if existing:
                return existing
        return self.create_session(customer_id=customer_id, tenant_id=tenant_id)

    def save_session(self, session: SessionMemory):
        session.updated_at = datetime.utcnow()
        data = self._load_json(SESSIONS_FILE)
        data[session.session_id] = session.dict()
        self._save_json(SESSIONS_FILE, data)

    # ---------------- Case ----------------
    def get_case(self, case_id: str) -> Optional[CaseMemory]:
        data = self._load_json(CASES_FILE)
        raw = data.get(case_id)
        return CaseMemory(**raw) if raw else None

    def create_case(
        self,
        session_id: str,
        customer_id: str,
        tenant_id: str,
        order_id: Optional[str] = None,
        issue_type: Optional[str] = None
    ) -> CaseMemory:
        case = CaseMemory(
            session_id=session_id,
            customer_id=customer_id,
            tenant_id=tenant_id,
            order_id=order_id,
            issue_type=issue_type
        )
        data = self._load_json(CASES_FILE)
        data[case.case_id] = case.dict()
        self._save_json(CASES_FILE, data)
        return case

    def save_case(self, case: CaseMemory):
        case.updated_at = datetime.utcnow()
        data = self._load_json(CASES_FILE)
        data[case.case_id] = case.dict()
        self._save_json(CASES_FILE, data)

    def get_or_create_active_case(self, session: SessionMemory) -> CaseMemory:
        if session.active_case_id:
            case = self.get_case(session.active_case_id)
            if case and case.status in ["open", "waiting_customer", "escalated"]:
                return case

        case = self.create_case(
            session_id=session.session_id,
            customer_id=session.customer_id,
            tenant_id=session.tenant_id
        )
        session.active_case_id = case.case_id
        self.save_session(session)
        return case

    # ---------------- Helpers ----------------
    def append_message(self, session: SessionMemory, role: str, content: str):
        session.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        # keep last 20 messages only
        session.messages = session.messages[-20:]
        self.save_session(session)

    def to_state_context(self, session: SessionMemory, case: CaseMemory) -> Dict[str, Any]:
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
            "recent_messages": session.messages[-6:]
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
        status: Optional[str] = None
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
            # merge unique
            merged = list(case.tools_executed)
            for t in tools_executed:
                if t not in merged:
                    merged.append(t)
            case.tools_executed = merged
        if tool_results_summary is not None:
            case.tool_results_summary.update(tool_results_summary)
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