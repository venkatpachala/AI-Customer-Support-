"""Searchable journey records. Routers stay thin and call these helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, or_, select

from config.tenant_contract import load_platform_tenant, platform_tenant_yaml_path
from db.models import (
    CaseRow,
    HumanTaskRow,
    InteractionRow,
    PlatformEventRow,
    WorkflowRunRow,
    WorkflowStepRow,
)
from db.session import SessionLocal
from interactions.outcomes import classify_outcome, classify_sub_intent

_VERSIONS: Dict[str, Dict[str, str]] = {}
_KIND_ORDER = {"message": 0, "workflow": 1, "step": 2, "approval": 3, "event": 4}
_TEXT_LIMIT = 240


class IntelligenceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def tenant_versions(tenant_id: str) -> Dict[str, str]:
    cached = _VERSIONS.get(tenant_id)
    if cached is not None:
        return cached
    unversioned = {
        "agent": "unversioned",
        "policy_pack": "unversioned",
        "knowledge_snapshot": "unversioned",
    }
    try:
        if not platform_tenant_yaml_path(tenant_id).is_file():
            payload = dict(unversioned)
        else:
            tenant = load_platform_tenant(tenant_id)
            payload = {
                "agent": tenant.versions.agent or "unversioned",
                "policy_pack": tenant.versions.policy_pack or "unversioned",
                "knowledge_snapshot": tenant.versions.knowledge_snapshot or "unversioned",
            }
    except Exception:
        payload = dict(unversioned)
    _VERSIONS[tenant_id] = payload
    return payload


def stamp_turn_metadata(
    *,
    tenant_id: str,
    message: str,
    status: Optional[str],
    blocked: bool,
    escalated: bool,
    missing_inputs: Optional[List[Any]],
    photos_received: bool,
    metadata: Optional[Dict[str, Any]],
    channel: str = "chat",
    session_factory=SessionLocal,
) -> Dict[str, Any]:
    """Fill the journey keys on metadata. Existing keys stay."""
    meta = _scrub_secrets(dict(metadata or {}))
    policy = meta.get("policy_decision") if isinstance(meta.get("policy_decision"), dict) else {}
    slots = meta.get("slots") if isinstance(meta.get("slots"), dict) else {}
    workflow_status = meta.get("workflow_status")
    run_id = meta.get("workflow_run_id")
    pending = str(workflow_status or "") == "waiting_approval" or _pending_approval(run_id, session_factory)
    versions = tenant_versions(tenant_id)
    reason = meta.get("reason") or slots.get("reason")
    outcome = classify_outcome(
        blocked=blocked,
        escalated=escalated,
        status=status,
        workflow_status=None if workflow_status is None else str(workflow_status),
        case_status=meta.get("case_status"),
        missing_inputs=missing_inputs,
        photos_received=photos_received,
        pending_approval=pending,
    )
    turn_channel = str(meta.get("channel") or channel or "chat")
    if turn_channel not in {"chat", "voice"}:
        turn_channel = "chat"
    meta["outcome"] = outcome
    meta["sub_intent"] = classify_sub_intent(message, None if reason is None else str(reason))
    meta["workflow_run_id"] = run_id
    meta["workflow_status"] = workflow_status
    meta["policy_version"] = (
        policy.get("policy_version") or meta.get("policy_version") or versions["policy_pack"]
    )
    meta["policy_deny_code"] = (
        meta.get("policy_deny_code")
        if meta.get("policy_deny_code") is not None
        else meta.get("deny_code", policy.get("deny_code"))
    )
    meta["agent_version"] = versions["agent"]
    meta["knowledge_snapshot"] = versions["knowledge_snapshot"]
    meta["channel"] = turn_channel
    return meta


def record_turn(service: Any = None, **kwargs: Any):
    """Thin wrapper the runtime uses for one chat turn."""
    if service is None:
        from interactions.service import InteractionService

        service = InteractionService()
    return service.log_chat_turn(**kwargs)


def list_interactions(
    *,
    tenant_id: str,
    customer_id: Optional[str] = None,
    case_id: Optional[str] = None,
    outcome: Optional[str] = None,
    intent: Optional[str] = None,
    escalated: Optional[bool] = None,
    limit: int = 20,
    session_factory=SessionLocal,
) -> List[Dict[str, Any]]:
    """Newest first. Items are a fixed field set, never tool payloads."""
    limit = max(1, min(int(limit or 20), 100))
    with session_factory() as db:
        stmt = select(InteractionRow).where(InteractionRow.tenant_id == tenant_id)
        if customer_id:
            stmt = stmt.where(InteractionRow.customer_id == customer_id)
        if case_id:
            stmt = stmt.where(InteractionRow.case_id == case_id)
        if intent:
            stmt = stmt.where(InteractionRow.intent == intent)
        if escalated is not None:
            stmt = stmt.where(InteractionRow.escalated.is_(bool(escalated)))
        stmt = stmt.order_by(desc(InteractionRow.created_at))
        # Outcome lives in metadata. Pull a bounded window, then keep matches.
        window = limit if not outcome else max(limit, 500)
        rows = db.execute(stmt.limit(window)).scalars().all()
    items: List[Dict[str, Any]] = []
    for row in rows:
        view = _public_item(row)
        if outcome and view["outcome"] != outcome:
            continue
        items.append(view)
        if len(items) >= limit:
            break
    return items


def case_timeline(case_id: str, tenant_id: str, session_factory=SessionLocal) -> Dict[str, Any]:
    """Oldest first: chat, workflow, steps, approvals, and case events."""
    with session_factory() as db:
        case = db.get(CaseRow, case_id)
        if case is None or case.tenant_id != tenant_id:
            raise IntelligenceError(404, "case not found")
        interactions = db.execute(
            select(InteractionRow)
            .where(InteractionRow.case_id == case_id)
            .where(InteractionRow.tenant_id == tenant_id)
            .order_by(InteractionRow.created_at.asc())
        ).scalars().all()
        runs = db.execute(
            select(WorkflowRunRow)
            .where(WorkflowRunRow.case_id == case_id)
            .where(WorkflowRunRow.tenant_id == tenant_id)
            .order_by(WorkflowRunRow.created_at.asc())
        ).scalars().all()
        run_ids = [row.id for row in runs]
        steps = []
        if run_ids:
            steps = db.execute(
                select(WorkflowStepRow)
                .where(WorkflowStepRow.run_id.in_(run_ids))
                .order_by(WorkflowStepRow.created_at.asc())
            ).scalars().all()
        tasks = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.case_id == case_id)
            .where(HumanTaskRow.tenant_id == tenant_id)
            .order_by(HumanTaskRow.created_at.asc())
        ).scalars().all()
        events = db.execute(
            select(PlatformEventRow)
            .where(PlatformEventRow.tenant_id == tenant_id)
            .where(
                or_(
                    PlatformEventRow.case_id == case_id,
                    PlatformEventRow.payload_json["case_id"].as_string() == case_id,
                )
            )
            .order_by(PlatformEventRow.created_at.asc())
        ).scalars().all()

    items: List[Dict[str, Any]] = []
    for row in interactions:
        items.append(_message_item(row, "user", row.message))
        items.append(_message_item(row, "assistant", row.response))
    for row in runs:
        items.append(
            {
                "at": _iso(row.created_at),
                "kind": "workflow",
                "title": f"{row.workflow_name} {row.status}",
                "ref": row.id,
                "data": {
                    "workflow": row.workflow_name,
                    "status": row.status,
                    "error": row.error,
                },
                "_sort": (row.created_at or datetime.min, 0),
            }
        )
    for row in steps:
        items.append(
            {
                "at": _iso(row.started_at or row.created_at),
                "kind": "step",
                "title": row.step_name,
                "ref": row.id,
                "data": {
                    "step_name": row.step_name,
                    "status": row.status,
                    "attempt": row.attempt,
                },
                "_sort": (row.started_at or row.created_at or datetime.min, 0),
            }
        )
    for row in tasks:
        payload = dict(row.payload_json or {})
        items.append(
            {
                "at": _iso(row.created_at),
                "kind": "approval",
                "title": f"{row.task_type} {row.status}",
                "ref": row.id,
                "data": {
                    "type": row.task_type,
                    "status": row.status,
                    "amount": payload.get("amount"),
                    "order_id": payload.get("order_id"),
                },
                "_sort": (row.created_at or datetime.min, 0),
            }
        )
    for row in events:
        items.append(
            {
                "at": _iso(row.created_at),
                "kind": "event",
                "title": row.event_type,
                "ref": row.id,
                "data": {"event_type": row.event_type},
                "_sort": (row.created_at or datetime.min, 0),
            }
        )
    items.sort(key=lambda item: (_sort_key(item.get("_sort")), _KIND_ORDER.get(item["kind"], 9), item["title"]))
    for item in items:
        item.pop("_sort", None)
    return {"case_id": case_id, "tenant_id": tenant_id, "items": items}


def intent_rollup(
    tenant_id: str,
    since: Optional[str] = None,
    session_factory=SessionLocal,
) -> Dict[str, Any]:
    cutoff = _parse_since(since)
    with session_factory() as db:
        rows = db.execute(
            select(InteractionRow)
            .where(InteractionRow.tenant_id == tenant_id)
            .where(InteractionRow.created_at >= cutoff)
        ).scalars().all()
    by_intent: Dict[str, int] = {}
    by_outcome: Dict[str, int] = {}
    escalated = 0
    waiting_approval = 0
    for row in rows:
        intent = row.intent or "unknown"
        by_intent[intent] = by_intent.get(intent, 0) + 1
        meta = dict(row.metadata_json or {})
        outcome = meta.get("outcome") or classify_outcome(
            blocked=bool(row.blocked),
            escalated=bool(row.escalated),
            status=row.status,
            workflow_status=meta.get("workflow_status"),
            missing_inputs=list(row.missing_inputs or []),
            photos_received=bool(row.photos_received),
        )
        outcome = str(outcome)
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if row.escalated:
            escalated += 1
        if outcome == "waiting_approval":
            waiting_approval += 1
    return {
        "tenant_id": tenant_id,
        "since": _iso(cutoff),
        "n": len(rows),
        "by_intent": by_intent,
        "by_outcome": by_outcome,
        "escalated": escalated,
        "waiting_approval": waiting_approval,
    }


def _scrub_secrets(value: Any) -> Any:
    """Drop token-like keys before the row is stored. User text stays on the message column."""
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            if _secret_key(str(key)):
                continue
            cleaned[key] = _scrub_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub_secrets(item) for item in value]
    return value


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in ("secret", "token", "password", "api_key", "apikey", "authorization"))


def _pending_approval(run_id: Optional[str], session_factory) -> bool:
    if not run_id:
        return False
    with session_factory() as db:
        row = db.execute(
            select(HumanTaskRow.id)
            .where(HumanTaskRow.workflow_run_id == run_id)
            .where(HumanTaskRow.task_type == "refund_approval")
            .where(HumanTaskRow.status == "pending")
            .limit(1)
        ).first()
        return row is not None


def _public_item(row: InteractionRow) -> Dict[str, Any]:
    meta = dict(row.metadata_json or {})
    outcome = meta.get("outcome") or classify_outcome(
        blocked=bool(row.blocked),
        escalated=bool(row.escalated),
        status=row.status,
        workflow_status=meta.get("workflow_status"),
        missing_inputs=list(row.missing_inputs or []),
        photos_received=bool(row.photos_received),
    )
    return {
        "id": row.interaction_id,
        "created_at": _iso(row.created_at),
        "customer_id": row.customer_id,
        "case_id": row.case_id,
        "intent": row.intent,
        "sub_intent": meta.get("sub_intent") or "other",
        "outcome": outcome,
        "order_id": row.order_id,
        "escalated": bool(row.escalated),
        "workflow_run_id": meta.get("workflow_run_id"),
        "workflow_status": meta.get("workflow_status"),
        "latency_ms": float(row.latency_ms or 0.0),
        "request_id": row.request_id,
    }


def _message_item(row: InteractionRow, role: str, text: Optional[str]) -> Dict[str, Any]:
    body = str(text or "")
    if len(body) > _TEXT_LIMIT:
        body = body[:_TEXT_LIMIT]
    role_rank = 0 if role == "user" else 1
    return {
        "at": _iso(row.created_at),
        "kind": "message",
        "title": role,
        "ref": row.interaction_id,
        "data": {"role": role, "text": body},
        "_sort": (row.created_at or datetime.min, role_rank),
    }


def _parse_since(since: Optional[str]) -> datetime:
    if not since:
        return datetime.utcnow() - timedelta(days=7)
    text = str(since).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise IntelligenceError(400, "since must be an ISO date") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def _sort_key(value: Any) -> tuple:
    if isinstance(value, tuple) and value:
        moment = value[0] if isinstance(value[0], datetime) else datetime.min
        rank = value[1] if len(value) > 1 else 0
        return (moment, rank)
    if isinstance(value, datetime):
        return (value, 0)
    return (datetime.min, 0)
