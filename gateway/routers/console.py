"""Owner console and the public site. Server-rendered. One CSS file."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from controlplane.connections import list_cards, probe_connection, save_connection
from controlplane.keys import (
    ensure_tenant,
    issue_key,
    list_keys,
    rotate_key,
    set_killed,
    set_live_enabled,
    take_unrevealed,
    tenant_record,
)
from controlplane.purge import queue_purge, run_purge
from controlplane.knowledge import (
    delete_snapshot,
    list_documents,
    reingest_snapshot,
    store_pdf,
    uploads_allowed,
    use_sample_pack,
)
from controlplane.ratelimit import login_allowed, note_login_failure, note_login_success, signup_allowed
from controlplane.sandbox import STEPS, judge
from controlplane.turns import run_product_chat
from controlplane.webhooks import get_endpoint, save_endpoint
from db.models import CaseRow, HumanTaskRow, IntakeRequestRow
from db.session import SessionLocal
from identity.accounts import signup, tenant_for_credentials
from identity.owner_session import COOKIE_NAME, TTL_SECONDS, issue_owner_token, read_owner
from identity.session import create_customer_session
from interactions.intelligence import IntelligenceError, case_timeline, list_interactions
from sqlalchemy import select
from workflows.approvals import ApprovalError, approve_task, list_tasks, reject_task

router = APIRouter(tags=["console"])
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def _owner(request: Request) -> str | None:
    return read_owner(request.cookies.get(COOKIE_NAME))


def _require(request: Request) -> str:
    tenant = _owner(request)
    if not tenant:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    ensure_tenant(tenant)
    return tenant


def _render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("error", request.query_params.get("error"))
    context.setdefault("section", "")
    return _TEMPLATES.TemplateResponse(
        request,
        template,
        {"request": request, **context},
        status_code=status_code,
    )


def _wants_json(request: Request) -> bool:
    content_type = (request.headers.get("content-type") or "").lower()
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in content_type or "application/json" in accept


async def _email_password(request: Request) -> tuple[str, str]:
    if _wants_json(request) and "application/json" in (request.headers.get("content-type") or "").lower():
        body = await request.json()
        return str(body.get("email") or ""), str(body.get("password") or "")
    form = await request.form()
    return str(form.get("email") or ""), str(form.get("password") or "")


def _owner_cookie(response, tenant_id: str, request: Request):
    response.set_cookie(
        key=COOKIE_NAME,
        value=issue_owner_token(tenant_id),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=TTL_SECONDS,
        path="/",
    )
    return response


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host or "unknown"


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _render(request, "home.html")


@router.get("/docs", response_class=HTMLResponse)
def docs(request: Request):
    return _render(request, "docs.html")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if _owner(request):
        return RedirectResponse("/app/inbox", status_code=303)
    return _render(request, "login.html")


@router.post("/login")
async def login_submit(request: Request):
    email, password = await _email_password(request)
    allowed, reason = login_allowed(email)
    if not allowed:
        if _wants_json(request):
            return JSONResponse({"detail": reason}, status_code=429)
        return _render(request, "login.html", status_code=429, error=reason)
    tenant = tenant_for_credentials(email, password)
    if not tenant:
        note_login_failure(email)
        if _wants_json(request):
            return JSONResponse({"detail": "invalid credentials"}, status_code=401)
        return _render(request, "login.html", status_code=401, error="Invalid email or password")
    note_login_success(email)
    if _wants_json(request):
        response = JSONResponse({"ok": True, "tenant_id": tenant})
    else:
        response = RedirectResponse("/app/inbox", status_code=303)
    return _owner_cookie(response, tenant, request)


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    if _owner(request):
        return RedirectResponse("/app/inbox", status_code=303)
    return _render(request, "signup.html")


@router.post("/signup")
async def signup_submit(request: Request):
    allowed, reason = signup_allowed(_client_ip(request))
    if not allowed:
        if _wants_json(request):
            return JSONResponse({"detail": reason}, status_code=429)
        return _render(request, "signup.html", status_code=429, error=reason)
    email, password = await _email_password(request)
    try:
        account = signup(email, password)
    except ValueError as exc:
        if _wants_json(request):
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return _render(request, "signup.html", status_code=400, error=str(exc))
    if _wants_json(request):
        take_unrevealed(account["tenant_id"], role="widget", mode="test")
        take_unrevealed(account["tenant_id"], role="supervisor", mode="test")
        response = JSONResponse(
            {
                "tenant_id": account["tenant_id"],
                "widget_key": account["widget_key"],
                "supervisor_key": account["supervisor_key"],
            },
            status_code=201,
        )
    else:
        response = RedirectResponse("/app/install", status_code=303)
    return _owner_cookie(response, account["tenant_id"], request)


@router.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/app")
def app_home(request: Request):
    _require(request)
    return RedirectResponse("/app/inbox", status_code=303)


@router.get("/app/inbox", response_class=HTMLResponse)
def inbox(request: Request, filter: str = "all"):
    tenant = _require(request)
    filt = filter if filter in {"all", "escalated", "waiting_approval"} else "all"
    kwargs = {"tenant_id": tenant, "limit": 50}
    if filt == "escalated":
        kwargs["escalated"] = True
    elif filt == "waiting_approval":
        kwargs["outcome"] = "waiting_approval"
    items = [item for item in list_interactions(**kwargs) if item.get("case_id")]
    return _render(request, "inbox.html", section="inbox", items=items, filt=filt)


@router.get("/app/cases/{case_id}", response_class=HTMLResponse)
def case_page(request: Request, case_id: str):
    tenant = _require(request)
    try:
        timeline = case_timeline(case_id, tenant)
    except IntelligenceError:
        return _render(
            request,
            "case.html",
            section="inbox",
            case_id=case_id,
            items=[],
            error="Case not found",
            workflow_status=None,
            order_id=None,
            auth_level="—",
            missing_inputs="",
            run_id=None,
            task_id=None,
        )
    with SessionLocal() as db:
        case = db.get(CaseRow, case_id)
        task = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.case_id == case_id)
            .where(HumanTaskRow.tenant_id == tenant)
            .where(HumanTaskRow.status == "pending")
        ).scalars().first()
        task_id = None if task is None else task.id
    run_id = None
    for item in timeline["items"]:
        if item.get("kind") == "workflow":
            run_id = item.get("ref")
    status = None if case is None else case.status
    workflow_status = status
    for item in reversed(timeline["items"]):
        data = item.get("data") or {}
        if item.get("kind") == "workflow" and data.get("status"):
            workflow_status = data["status"]
            break
    missing = ""
    if case is not None:
        missing = ", ".join(str(item) for item in (case.missing_inputs or []))
    return _render(
        request,
        "case.html",
        section="inbox",
        case_id=case_id,
        items=timeline["items"],
        workflow_status=workflow_status,
        order_id=None if case is None else case.order_id,
        auth_level=None if case is None else case.auth_level,
        missing_inputs=missing,
        run_id=run_id,
        task_id=task_id,
    )


@router.get("/app/approvals", response_class=HTMLResponse)
def approvals_page(request: Request):
    tenant = _require(request)
    return _render(
        request,
        "approvals.html",
        section="approvals",
        approvals=list_tasks(tenant_id=tenant, status="pending"),
        notice=request.query_params.get("notice"),
    )


def _decide(request: Request, task_id: str, kind: str, note: str | None):
    tenant = _require(request)
    try:
        if kind == "approve":
            approve_task(task_id, tenant_id=tenant, actor_id="owner", note=note)
            notice = "Approved"
        else:
            if not (note or "").strip():
                return RedirectResponse("/app/approvals?error=Reject+note+is+required", status_code=303)
            reject_task(task_id, tenant_id=tenant, actor_id="owner", note=note.strip())
            notice = "Rejected"
    except ApprovalError as exc:
        notice = exc.detail
    return RedirectResponse(f"/app/approvals?notice={notice.replace(' ', '+')}", status_code=303)


@router.post("/app/approvals/{task_id}/approve")
def approve_from_app(request: Request, task_id: str):
    return _decide(request, task_id, "approve", None)


@router.post("/app/approvals/{task_id}/reject")
def reject_from_app(request: Request, task_id: str, note: str = Form("")):
    return _decide(request, task_id, "reject", note)


@router.get("/app/sandbox", response_class=HTMLResponse)
def sandbox_page(request: Request):
    tenant = _require(request)
    row = tenant_record(tenant)
    return _render(
        request,
        "sandbox.html",
        section="sandbox",
        passed=bool(row and row.sandbox_passed_at),
        turn=None,
        steps=None,
        citations="",
        workflow_status="",
        missing="",
        tools=[],
    )


async def _owner_turn(request: Request, tenant: str, message: str) -> dict:
    session = create_customer_session(tenant, "sandbox")
    return await run_product_chat(
        request,
        tenant_id=tenant,
        customer_ref="sandbox",
        message=message,
        session_cookie=session.id,
        force_mock=True,
    )


@router.post("/app/sandbox/send", response_class=HTMLResponse)
async def sandbox_send(request: Request, message: str = Form(...)):
    tenant = _require(request)
    turn = await _owner_turn(request, tenant, message)
    row = tenant_record(tenant)
    return _render(
        request,
        "sandbox.html",
        section="sandbox",
        passed=bool(row and row.sandbox_passed_at),
        turn={"message": message, "response": turn.get("response") or turn.get("error") or ""},
        steps=None,
        citations=", ".join(str(item) for item in (turn.get("citations") or [])),
        workflow_status=turn.get("workflow_status") or "",
        missing=", ".join(str(item) for item in (turn.get("missing_inputs") or [])),
        tools=_tool_names(turn),
    )


@router.post("/app/sandbox/run", response_class=HTMLResponse)
async def sandbox_script(request: Request):
    tenant = _require(request)
    turns = []
    for step in STEPS:
        turns.append(await _owner_turn(request, tenant, step["message"]))
    report = judge(turns)
    if report["passed"]:
        from controlplane.keys import mark_sandbox_passed

        mark_sandbox_passed(tenant)
    row = tenant_record(tenant)
    last = turns[-1] if turns else {}
    return _render(
        request,
        "sandbox.html",
        section="sandbox",
        passed=bool(row and row.sandbox_passed_at),
        turn={"message": STEPS[-1]["message"], "response": last.get("response") or ""},
        steps=report["steps"],
        citations=", ".join(str(item) for item in (last.get("citations") or [])),
        workflow_status=last.get("workflow_status") or "",
        missing=", ".join(str(item) for item in (last.get("missing_inputs") or [])),
        tools=_tool_names(last),
        error=None if report["passed"] else "Sandbox did not pass",
    )


def _tool_names(turn: dict) -> list[str]:
    names: list[str] = []
    raw = turn.get("tools_used") or turn.get("tool_calls") or []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item:
                names.append(item)
            elif isinstance(item, dict):
                label = item.get("name") or item.get("tool") or ""
                if label:
                    names.append(str(label))
    status = turn.get("workflow_status") or ""
    if status:
        names.append(f"workflow refund → {status}")
    return names


@router.post("/app/sandbox/voice")
async def sandbox_voice(request: Request):
    """Voice is another client of the same chat turn. The browser sends the transcript."""
    tenant = _require(request)
    body = await request.json()
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"detail": "message is required"}, status_code=400)
    turn = await _owner_turn(request, tenant, message)
    return JSONResponse(
        {
            "message": message,
            "response": turn.get("response") or turn.get("error") or "",
            "workflow_status": turn.get("workflow_status") or "",
            "citations": turn.get("citations") or [],
            "missing_inputs": turn.get("missing_inputs") or [],
            "case_id": turn.get("case_id") or "",
            "tools": _tool_names(turn),
        }
    )


@router.get("/app/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request):
    tenant = _require(request)
    return _render(
        request,
        "knowledge.html",
        section="knowledge",
        documents=list_documents(tenant),
        uploads_open=uploads_allowed(tenant),
        tenant=tenant,
    )


@router.post("/app/knowledge/upload", response_class=HTMLResponse)
async def knowledge_upload(request: Request, file: UploadFile = File(...)):
    tenant = _require(request)
    data = await file.read()
    error = None
    try:
        store_pdf(tenant, file.filename or "upload.pdf", data)
    except Exception as exc:
        error = str(exc)
    return _render(
        request,
        "knowledge.html",
        section="knowledge",
        documents=list_documents(tenant),
        uploads_open=uploads_allowed(tenant),
        tenant=tenant,
        error=error,
    )


@router.post("/app/knowledge/{snapshot_id}/delete")
def knowledge_delete(request: Request, snapshot_id: str):
    tenant = _require(request)
    try:
        delete_snapshot(tenant, snapshot_id)
    except Exception as exc:
        return RedirectResponse(f"/app/knowledge?error={str(exc)[:180]}", status_code=303)
    return RedirectResponse("/app/knowledge", status_code=303)


@router.post("/app/knowledge/{snapshot_id}/reingest")
def knowledge_reingest(request: Request, snapshot_id: str):
    tenant = _require(request)
    try:
        reingest_snapshot(tenant, snapshot_id)
    except Exception as exc:
        return RedirectResponse(f"/app/knowledge?error={str(exc)[:180]}", status_code=303)
    return RedirectResponse("/app/knowledge", status_code=303)


@router.post("/app/knowledge/sample")
def knowledge_sample(request: Request):
    tenant = _require(request)
    try:
        use_sample_pack(tenant)
    except Exception as exc:
        return RedirectResponse(f"/app/knowledge?error={str(exc)[:180]}", status_code=303)
    return RedirectResponse("/app/knowledge", status_code=303)


@router.get("/app/connections", response_class=HTMLResponse)
def connections_page(request: Request):
    tenant = _require(request)
    row = tenant_record(tenant)
    return _render(
        request,
        "connections.html",
        section="connections",
        cards=list_cards(
            tenant,
            sandbox_passed=bool(row and row.sandbox_passed_at),
            live_enabled=bool(row and row.live_enabled_at),
        ),
        check=request.query_params.get("check"),
    )


@router.post("/app/connections/{provider}")
def connections_save(
    request: Request,
    provider: str,
    shop_domain: str = Form(""),
    token: str = Form(""),
):
    tenant = _require(request)
    try:
        save_connection(tenant, provider, shop_domain=shop_domain, token=token)
    except ValueError as exc:
        return RedirectResponse(f"/app/connections?error={exc}", status_code=303)
    return RedirectResponse("/app/connections", status_code=303)


@router.post("/app/connections/{provider}/test")
def connections_test(request: Request, provider: str):
    tenant = _require(request)
    result = probe_connection(tenant, provider)
    detail = result["detail"].replace(" ", "+")
    return RedirectResponse(f"/app/connections?check={detail}", status_code=303)


def _key_context(request: Request, tenant: str) -> dict:
    row = tenant_record(tenant)
    keys = list_keys(tenant)
    test = next((item for item in keys if item["role"] == "widget" and item["mode"] == "test" and not item["revoked_at"]), None)
    live = next((item for item in keys if item["role"] == "widget" and item["mode"] == "live" and not item["revoked_at"]), None)
    supervisor = next((item for item in keys if item["role"] == "supervisor" and item["mode"] == "test" and not item["revoked_at"]), None)
    hook = get_endpoint(tenant) or {}
    origin = str(request.base_url).rstrip("/")
    return {
        "section": "install",
        "tenant": tenant,
        "origin": origin,
        "sandbox_passed": bool(row and row.sandbox_passed_at),
        "live_enabled": bool(row and row.live_enabled_at),
        "killed": bool(row and row.killed_at),
        "test_prefix": None if test is None else test["prefix"],
        "live_prefix": None if live is None else live["prefix"],
        "supervisor_prefix": None if supervisor is None else supervisor["prefix"],
        "test_secret": take_unrevealed(tenant, role="widget", mode="test"),
        "supervisor_secret": take_unrevealed(tenant, role="supervisor", mode="test"),
        "live_secret": take_unrevealed(tenant, role="widget", mode="live"),
        "webhook_url": hook.get("url") or "",
        "last_status": hook.get("last_status"),
        "last_error": hook.get("last_error"),
    }


@router.get("/app/install", response_class=HTMLResponse)
def install_page(request: Request):
    tenant = _require(request)
    return _render(request, "install.html", **_key_context(request, tenant))


@router.post("/app/install/test-key")
def install_test_key(request: Request):
    tenant = _require(request)
    issue_key(tenant, role="widget", mode="test")
    return RedirectResponse("/app/install", status_code=303)


@router.post("/app/install/rotate-test-key")
def install_rotate_test_key(request: Request):
    tenant = _require(request)
    rotate_key(tenant, role="widget", mode="test")
    return RedirectResponse("/app/install", status_code=303)


@router.post("/app/install/purge")
def install_purge(request: Request, ops_password: str = Form("")):
    tenant = _require(request)
    expected = os.getenv("OPS_PASSWORD", "")
    given = hashlib.sha256((ops_password or "").encode("utf-8")).hexdigest()
    wanted = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    if not expected or not hmac.compare_digest(given, wanted):
        return RedirectResponse("/app/install?error=Admin+password+required", status_code=303)
    run_purge(tenant)
    return RedirectResponse("/app/install", status_code=303)


@router.post("/app/install/live-key")
def install_live_key(request: Request):
    tenant = _require(request)
    row = tenant_record(tenant)
    if row is None or row.sandbox_passed_at is None:
        return RedirectResponse("/app/install?error=Available+after+sandbox+pass", status_code=303)
    issue_key(tenant, role="widget", mode="live")
    return RedirectResponse("/app/install", status_code=303)


@router.post("/app/install/webhook")
def install_webhook(request: Request, url: str = Form(...)):
    tenant = _require(request)
    try:
        save_endpoint(tenant, url)
    except ValueError as exc:
        return RedirectResponse(f"/app/install?error={exc}", status_code=303)
    return RedirectResponse("/app/install", status_code=303)


@router.post("/app/install/kill")
def install_kill(request: Request):
    tenant = _require(request)
    row = tenant_record(tenant)
    set_killed(tenant, not bool(row and row.killed_at))
    return RedirectResponse("/app/install", status_code=303)


@router.post("/app/install/live")
def install_live(request: Request, ops_password: str = Form("")):
    """Admin enable. The brand password is not enough to turn on live shop calls."""
    tenant = _require(request)
    expected = os.getenv("OPS_PASSWORD", "")
    given = hashlib.sha256((ops_password or "").encode("utf-8")).hexdigest()
    wanted = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    if not expected or not hmac.compare_digest(given, wanted):
        return RedirectResponse("/app/install?error=Admin+password+required", status_code=303)
    row = tenant_record(tenant)
    try:
        set_live_enabled(tenant, not bool(row and row.live_enabled_at))
    except ValueError as exc:
        return RedirectResponse(f"/app/install?error={str(exc)[:180]}", status_code=303)
    return RedirectResponse("/app/install", status_code=303)


def _save_intake(kind: str, email: str, note: str, tenant_id: str | None = None) -> None:
    with SessionLocal() as db:
        db.add(
            IntakeRequestRow(
                id=str(uuid.uuid4()),
                kind=kind,
                email=(email or "").strip().lower()[:256],
                tenant_id=tenant_id,
                note=(note or "").strip()[:2000],
            )
        )
        db.commit()


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return _render(request, "privacy.html")


@router.post("/privacy/delete")
def privacy_delete(request: Request, email: str = Form(...), note: str = Form("")):
    tenant = _owner(request)
    _save_intake("deletion", email, note, tenant)
    if tenant:
        queue_purge(tenant, email, note)
    return _render(request, "privacy.html", error="Deletion request received. A person will process it. Stripe is not called.")


@router.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return _render(request, "terms.html")


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(request: Request):
    return _render(request, "pricing.html")


@router.get("/status", response_class=HTMLResponse)
def status_page(request: Request):
    return _render(request, "status.html")


@router.get("/support", response_class=HTMLResponse)
def support_page(request: Request):
    return _render(request, "support.html")


@router.post("/support")
def support_submit(request: Request, email: str = Form(...), note: str = Form(...)):
    _save_intake("stuck_case", email, note, _owner(request))
    return _render(request, "support.html", error="Received. This does not retry a payment.")


@router.get("/w/{tenant}", response_class=HTMLResponse)
def widget_page(request: Request, tenant: str):
    safe = "".join(ch for ch in tenant if ch.isalnum() or ch in {"_", "-"}) or "zepto"
    return _render(request, "widget.html", tenant_json=json.dumps(safe))
