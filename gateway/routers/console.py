"""Owner console and the public site. Server-rendered. One CSS file."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from controlplane.connections import list_cards, mock_health, save_connection
from controlplane.keys import ensure_tenant, issue_key, list_keys, set_killed, take_unrevealed, tenant_record
from controlplane.knowledge import list_documents, store_pdf, uploads_allowed, use_sample_pack
from controlplane.sandbox import STEPS, judge
from controlplane.turns import run_product_chat
from controlplane.webhooks import get_endpoint, save_endpoint
from db.models import CaseRow, HumanTaskRow
from db.session import SessionLocal
from identity.owner_session import COOKIE_NAME, TTL_SECONDS, credentials_match, issue_owner_token, read_owner
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


def _render(request: Request, template: str, **context) -> HTMLResponse:
    context.setdefault("error", request.query_params.get("error"))
    context.setdefault("section", "")
    return _TEMPLATES.TemplateResponse(request, template, {"request": request, **context})


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
def login_submit(email: str = Form(...), password: str = Form(...)):
    if not credentials_match(email, password):
        return RedirectResponse("/login?error=Invalid+email+or+password", status_code=303)
    response = RedirectResponse("/app/inbox", status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=issue_owner_token("zepto"),
        httponly=True,
        samesite="lax",
        max_age=TTL_SECONDS,
        path="/",
    )
    return response


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
        error=None if report["passed"] else "Sandbox did not pass",
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
        error=error,
    )


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
        cards=list_cards(tenant, sandbox_passed=bool(row and row.sandbox_passed_at)),
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
    _require(request)
    result = mock_health(provider)
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
        "killed": bool(row and row.killed_at),
        "test_prefix": None if test is None else test["prefix"],
        "live_prefix": None if live is None else live["prefix"],
        "supervisor_prefix": None if supervisor is None else supervisor["prefix"],
        "test_secret": take_unrevealed(tenant, role="widget", mode="test"),
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


@router.get("/w/{tenant}", response_class=HTMLResponse)
def widget_page(request: Request, tenant: str):
    safe = "".join(ch for ch in tenant if ch.isalnum() or ch in {"_", "-"}) or "zepto"
    return _render(request, "widget.html", tenant_json=json.dumps(safe))
