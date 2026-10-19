"""Customer-only verification, evidence and conversation delivery."""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update, func

from db.models import CaseRow, MessageRow, VerificationChallengeRow, EvidenceFileRow
from db.session import SessionLocal
from identity.session import load_customer_session
from controlplane.http import require_principal

router = APIRouter(prefix="/v1/customer", tags=["customer"])


def customer(request: Request):
    from identity.session import request_session_token
    session = load_customer_session(request_session_token(request))
    if session is None:
        raise HTTPException(401, "customer session required")
    return session


def own_case(db, case_id: str, session):
    case = db.get(CaseRow, case_id)
    if case is None or case.tenant_id != session.tenant_id or case.customer_id != session.customer_ref:
        raise HTTPException(404, "case not found")
    return case


class VerificationBody(BaseModel):
    case_id: str
    order_id: str = Field(min_length=1, max_length=64)


class CodeBody(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def _digest(challenge_id: str, code: str) -> str:
    key = os.getenv("OPS_SESSION_SECRET", "")
    if not key:
        raise HTTPException(503, "verification is not configured")
    return hmac.new(key.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


@router.post("/verification")
def request_verification(body: VerificationBody, request: Request):
    session = customer(request)
    with SessionLocal() as db:
        own_case(db, body.case_id, session)
        count = db.execute(select(func.count()).select_from(VerificationChallengeRow).where(
            VerificationChallengeRow.session_id == session.id,
            VerificationChallengeRow.created_at > datetime.utcnow() - timedelta(hours=1))).scalar_one()
        if count >= 5:
            raise HTTPException(429, "verification request limit reached")
    if not os.getenv("SMTP_HOST"):
        raise HTTPException(503, "email verification is not configured; contact support")
    from tools.base.context import ToolContext
    from tools.registry import TOOL_REGISTRY
    from controlplane.mode import force_tools_mode, reset_tools_mode
    from controlplane.keys import tenant_tools_live
    if not tenant_tools_live(session.tenant_id, key_mode="live"):
        raise HTTPException(409, "merchant connection is not enabled")
    token = force_tools_mode("live")
    try:
        tool = TOOL_REGISTRY.get("shopify_get_order")
        result = tool.execute({"order_id": body.order_id}, ToolContext(request_id=uuid.uuid4().hex, tenant_id=session.tenant_id))
        recipient = ((result.data or {}).get("customer") or {}).get("email") if result.status == "success" else None
    finally:
        reset_tools_mode(token)
    challenge_id, code = uuid.uuid4().hex, f"{secrets.randbelow(1000000):06d}"
    with SessionLocal() as db:
        db.add(VerificationChallengeRow(id=challenge_id, tenant_id=session.tenant_id,
            session_id=session.id, case_id=body.case_id, order_id=body.order_id,
            code_hash=_digest(challenge_id, code) if recipient else _digest(challenge_id, secrets.token_hex(16)),
            expires_at=datetime.utcnow() + timedelta(minutes=10)))
        if recipient:
            from controlplane.outbox import enqueue
            from controlplane.vault import seal
            enqueue(db, tenant_id=session.tenant_id, key="verify:" + challenge_id, kind="email",
                    payload={"to": recipient, "subject": "Verify your support request",
                             "sealed_text": seal(f"Your code is {code}. It expires in 10 minutes. Do not share it with anyone.")})
        db.commit()
    return {"challenge_id": challenge_id, "message": "If the order has a registered email, a code will be sent there."}


@router.post("/verification/{challenge_id}")
def confirm_verification(challenge_id: str, body: CodeBody, request: Request):
    session = customer(request)
    with SessionLocal() as db:
        changed = db.execute(update(VerificationChallengeRow).where(
            VerificationChallengeRow.id == challenge_id,
            VerificationChallengeRow.tenant_id == session.tenant_id,
            VerificationChallengeRow.session_id == session.id,
            VerificationChallengeRow.attempts < 5,
            VerificationChallengeRow.verified_at.is_(None),
            VerificationChallengeRow.expires_at > datetime.utcnow())
            .values(attempts=VerificationChallengeRow.attempts + 1)).rowcount
        if changed != 1:
            raise HTTPException(400, "code is invalid or expired")
        row = db.get(VerificationChallengeRow, challenge_id)
        if not hmac.compare_digest(row.code_hash, _digest(challenge_id, body.code)):
            db.commit()
            raise HTTPException(400, "code is invalid or expired")
        own_case(db, row.case_id, session)
        row.verified_at = datetime.utcnow()
        case = db.get(CaseRow, row.case_id)
        summary = dict(case.tool_results_summary or {})
        summary["verified_order_ids"] = list(set(summary.get("verified_order_ids", []) + [row.order_id]))
        summary["ownership_checked"] = True
        case.tool_results_summary = summary
        case.auth_level = "verified"
        db.commit()
    return {"verified": True}


@router.get("/cases/{case_id}/messages")
def messages(case_id: str, request: Request):
    session = customer(request)
    with SessionLocal() as db:
        own_case(db, case_id, session)
        rows = db.execute(select(MessageRow).where(MessageRow.case_id == case_id).order_by(MessageRow.id)).scalars().all()
        return {"items": [{"id": row.id, "role": row.role, "text": row.content} for row in rows]}


@router.post("/cases/{case_id}/evidence")
async def upload_evidence(case_id: str, request: Request, file: UploadFile = File(...)):
    session = customer(request)
    content = await file.read(5 * 1024 * 1024 + 1)
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "image must be under 5 MB")
    media_type = "image/png" if content.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if content.startswith(b"\xff\xd8\xff") else None
    if media_type is None:
        raise HTTPException(400, "only PNG and JPEG images are accepted")
    with SessionLocal() as db:
        case = own_case(db, case_id, session)
        count = db.execute(select(func.count()).select_from(EvidenceFileRow).where(EvidenceFileRow.case_id == case_id)).scalar_one()
        if count >= 5:
            raise HTTPException(400, "case already has five attachments")
        evidence_id = uuid.uuid4().hex
        db.add(EvidenceFileRow(id=evidence_id, tenant_id=session.tenant_id, case_id=case_id,
                              filename="customer-image", media_type=media_type, content=content))
        case.photos_received = True
        db.commit()
    return {"id": evidence_id, "case_id": case_id, "received": True}


@router.get("/evidence/{evidence_id}")
def read_evidence(evidence_id: str, request: Request):
    principal = require_principal(request)
    if principal.role != "supervisor":
        raise HTTPException(403, "operator credential required")
    with SessionLocal() as db:
        row = db.get(EvidenceFileRow, evidence_id)
        if row is None or row.tenant_id != principal.tenant_id:
            raise HTTPException(404, "evidence not found")
        return Response(row.content, media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="customer-image"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
