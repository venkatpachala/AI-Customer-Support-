"""Durable workflow runner.

start() inserts a workflow_runs row and walks steps until a wait, a failure,
or the last step. resume() reloads those rows and continues at the first
step that is not success. Stripe is never called from here unless the
policy snapshot already stored allowed=True, or a supervisor approved a
refund_approval task for an amount inside manager_max. That override lives
in execute_refund. It does not cover OUT_OF_POLICY or an amount above the
manager cap. A cancelled run is not resumed.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import CaseRow, HumanTaskRow, WorkflowRunRow, WorkflowStepRow
from db.session import SessionLocal
from workflows.context import WorkflowContext
from workflows.idempotency import build_idempotency_key, find_reusable_run
from workflows.registry import get_workflow
from workflows.retry import attempts_exhausted, backoff_seconds
from workflows.state import (
    POLICY_RESET_STEPS,
    RUN_FAILED,
    RUN_PENDING,
    RUN_RUNNING,
    RUN_RETRYING,
    RUN_CANCELLED,
    RUN_SUCCEEDED,
    RUN_WAITING_APPROVAL,
    RUN_WAITING_AUTH,
    RUN_WAITING_INPUT,
    STEP_FAILED,
    STEP_RETRY,
    STEP_SUCCESS,
    STEP_TO_RUN_STATUS,
    STEP_WAIT_APPROVAL,
    StepResult,
    StepRuntime,
    WorkflowRunView,
)
from workflows.tools import invoke_tool

_OUTPUT_KEYS = (
    "policy",
    "order",
    "denied",
    "stripe",
    "stripe_called",
    "notify",
    "next",
    "requires_inputs",
    "case_status",
    "skipped_tool",
    "cancel_tool",
)


class WorkflowEngine:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        tool_registry: Any = None,
        sleeper: Optional[Callable[[float], None]] = None,
    ):
        self.session_factory = session_factory
        self.tool_registry = tool_registry
        self.sleeper = sleeper or _default_sleep

    def start(
        self,
        name: str,
        ctx: WorkflowContext,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowRunView:
        definition = get_workflow(name)
        if not ctx.case_id:
            raise ValueError("case_id is required to persist a workflow run")
        key = idempotency_key or build_idempotency_key(
            ctx.tenant_id,
            ctx.case_id,
            definition.name,
            str(ctx.slots.get("order_id") or "").strip() or None,
        )
        existing = self._reusable(key)
        if existing is not None:
            return existing

        run_id = str(uuid.uuid4())
        registry = ctx.tool_registry if self.tool_registry is None else self.tool_registry
        stored = WorkflowContext(
            tenant_id=ctx.tenant_id,
            case_id=ctx.case_id,
            customer_id=ctx.customer_id,
            auth_level=ctx.auth_level,
            conversation_id=ctx.conversation_id,
            slots=dict(ctx.slots),
            tool_registry=registry,
            session_factory=self.session_factory,
        )
        try:
            with self.session_factory() as db:
                db.add(
                    WorkflowRunRow(
                        id=run_id,
                        tenant_id=stored.tenant_id,
                        case_id=stored.case_id,
                        workflow_name=definition.name,
                        status=RUN_RUNNING,
                        input_json=stored.snapshot(definition.name),
                        output_json={},
                        idempotency_key=key,
                        current_step=definition.steps[0][0],
                        started_at=datetime.utcnow(),
                    )
                )
                db.commit()
        except IntegrityError:
            raced = self._reusable(key)
            if raced is not None:
                return raced
            raise
        self._set_case_status(stored.case_id, "running_workflow")
        return self._execute(run_id, stored)

    def resume(self, run_id: str, *, slots: Optional[Dict[str, Any]] = None) -> WorkflowRunView:
        """Continue the same run. Pass slots when the customer answered a wait."""
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                raise KeyError(f"workflow run not found: {run_id}")
            if row.status in (RUN_SUCCEEDED, RUN_CANCELLED):
                return _view(row)
            if row.status == RUN_FAILED and not slots:
                return _view(row)
        if slots:
            self._merge_slots(run_id, slots)
        ctx = self._context_for(run_id)
        return self._execute(run_id, ctx)

    def _execute(self, run_id: str, ctx: WorkflowContext) -> WorkflowRunView:
        definition = get_workflow(self._workflow_name(run_id))
        self._update_run(run_id, status=RUN_RUNNING, error=None)
        for index, (step_name, fn) in enumerate(definition.steps):
            status = self._step_status(run_id, step_name)
            if status == STEP_SUCCESS:
                continue
            result = self._run_step(run_id, ctx, index, step_name, fn)
            self._merge_output(run_id, result)
            if result.status == STEP_SUCCESS:
                continue
            if result.status == STEP_WAIT_APPROVAL:
                self._ensure_human_task(run_id, ctx, result)
            run_status = STEP_TO_RUN_STATUS.get(result.status, RUN_FAILED)
            self._update_run(
                run_id,
                status=run_status,
                current_step=step_name,
                error=result.error,
                finished=run_status == RUN_FAILED,
            )
            self._apply_case_wait(ctx.case_id, run_status)
            return self._load_view(run_id)

        self._update_run(run_id, status=RUN_SUCCEEDED, current_step=None, error=None, finished=True)
        self._release_running_case(ctx.case_id)
        return self._load_view(run_id)

    def _run_step(self, run_id: str, ctx: WorkflowContext, index: int, step_name: str, fn) -> StepResult:
        attempt = self._current_attempt(run_id, step_name)
        while True:
            runtime = self._runtime(run_id, ctx, attempt)
            result = fn(runtime)
            self._save_step(run_id, index, step_name, attempt, result)
            if result.status != STEP_RETRY:
                return result
            if attempts_exhausted(attempt):
                exhausted = StepResult(
                    status=STEP_FAILED,
                    output=dict(result.output),
                    error=result.error or "retry_exhausted",
                )
                self._save_step(run_id, index, step_name, attempt, exhausted)
                return exhausted
            self._update_run(run_id, status=RUN_RETRYING, current_step=step_name, error=result.error)
            self.sleeper(backoff_seconds(attempt))
            attempt += 1

    def _runtime(self, run_id: str, ctx: WorkflowContext, attempt: int) -> StepRuntime:
        outputs = self._outputs(run_id)
        policy = dict(self._output(run_id).get("policy") or {})
        # A step that just wrote policy in a previous attempt is on the run.
        evaluate_output = outputs.get("evaluate_policy") or {}
        if evaluate_output.get("policy"):
            policy = dict(evaluate_output["policy"])

        def call_tool(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
            return invoke_tool(
                ctx.tool_registry,
                name,
                params,
                request_id=run_id,
                tenant_id=ctx.tenant_id,
                customer_id=ctx.customer_id,
                case_id=ctx.case_id,
                session_id=ctx.conversation_id,
            )

        return StepRuntime(
            ctx=ctx,
            run_id=run_id,
            attempt=attempt,
            outputs=outputs,
            policy=policy,
            call_tool=call_tool,
            session_factory=self.session_factory,
        )

    def _merge_slots(self, run_id: str, slots: Dict[str, Any]) -> None:
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                raise KeyError(f"workflow run not found: {run_id}")
            payload = dict(row.input_json or {})
            previous_slots = dict(payload.get("slots") or {})
            merged = dict(previous_slots)
            merged.update(slots)
            payload["slots"] = merged
            row.input_json = payload
            output = dict(row.output_json or {})
            output.pop("policy", None)
            row.output_json = output
            steps = db.execute(
                select(WorkflowStepRow).where(WorkflowStepRow.run_id == run_id)
            ).scalars().all()
            order_changed = "order_id" in slots and str(merged.get("order_id") or "") != str(
                previous_slots.get("order_id") or ""
            )
            for step in steps:
                reset = step.step_name in POLICY_RESET_STEPS
                if order_changed and step.step_name == "fetch_order":
                    reset = True
                if not reset:
                    continue
                step.status = RUN_PENDING
                step.output_json = {}
                step.error = None
                step.attempt = 1
                step.finished_at = None
            row.status = RUN_RUNNING
            row.error = None
            row.finished_at = None
            row.updated_at = datetime.utcnow()
            db.commit()

    def _ensure_human_task(self, run_id: str, ctx: WorkflowContext, result: StepResult) -> None:
        task = result.human_task or {}
        task_type = str(task.get("type") or "refund_approval")
        with self.session_factory() as db:
            existing = db.execute(
                select(HumanTaskRow)
                .where(HumanTaskRow.workflow_run_id == run_id)
                .where(HumanTaskRow.task_type == task_type)
                .where(HumanTaskRow.status == "pending")
            ).scalars().first()
            if existing is not None:
                return
            db.add(
                HumanTaskRow(
                    id=str(uuid.uuid4()),
                    tenant_id=ctx.tenant_id,
                    case_id=ctx.case_id,
                    workflow_run_id=run_id,
                    task_type=task_type,
                    status="pending",
                    payload_json=dict(task.get("payload") or {}),
                )
            )
            db.commit()

    def _apply_case_wait(self, case_id: str, run_status: str) -> None:
        if run_status == RUN_WAITING_INPUT:
            self._set_case_status(case_id, "waiting_customer")
        elif run_status == RUN_WAITING_APPROVAL:
            self._set_case_status(case_id, "waiting_approval")
        elif run_status == RUN_FAILED:
            self._set_case_status(case_id, "open")

    def _release_running_case(self, case_id: str) -> None:
        """A finished non-refund run must not leave the case looking in-progress.

        The refund success path sets ``resolved`` itself. This only moves a
        case that is still ``running_workflow``.
        """
        if not case_id:
            return
        with self.session_factory() as db:
            row = db.get(CaseRow, case_id)
            if row is None or row.status != "running_workflow":
                return
            row.status = "open"
            row.updated_at = datetime.utcnow()
            db.commit()

    def _set_case_status(self, case_id: str, status: str) -> None:
        if not case_id:
            return
        with self.session_factory() as db:
            row = db.get(CaseRow, case_id)
            if row is None:
                return
            row.status = status
            row.updated_at = datetime.utcnow()
            db.commit()

    def _save_step(self, run_id: str, index: int, step_name: str, attempt: int, result: StepResult) -> None:
        with self.session_factory() as db:
            row = db.execute(
                select(WorkflowStepRow)
                .where(WorkflowStepRow.run_id == run_id)
                .where(WorkflowStepRow.step_name == step_name)
            ).scalars().first()
            now = datetime.utcnow()
            if row is None:
                row = WorkflowStepRow(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    step_name=step_name,
                    step_index=index,
                    status=result.status,
                    attempt=attempt,
                    input_json={},
                    output_json=dict(result.output or {}),
                    error=result.error,
                    started_at=now,
                )
                db.add(row)
            else:
                row.status = result.status
                row.step_index = index
                row.attempt = attempt
                row.output_json = dict(result.output or {})
                row.error = result.error
                if row.started_at is None:
                    row.started_at = now
            if result.status != STEP_RETRY:
                row.finished_at = now
            db.commit()

    def _merge_output(self, run_id: str, result: StepResult) -> None:
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                return
            output = dict(row.output_json or {})
            for key in _OUTPUT_KEYS:
                if key in (result.output or {}):
                    output[key] = result.output[key]
            if "order" in (result.output or {}):
                output["order"] = result.output["order"]
            row.output_json = output
            row.updated_at = datetime.utcnow()
            db.commit()

    def _update_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        current_step: Optional[str] = None,
        error: Optional[str] = None,
        finished: bool = False,
    ) -> None:
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                return
            if status is not None:
                row.status = status
            if current_step is not None or status == RUN_SUCCEEDED:
                row.current_step = current_step
            row.error = error
            row.updated_at = datetime.utcnow()
            if finished:
                row.finished_at = datetime.utcnow()
            db.commit()

    def _reusable(self, key: str) -> Optional[WorkflowRunView]:
        with self.session_factory() as db:
            row = find_reusable_run(db, key)
            if row is None:
                return None
            return _view(row)

    def _context_for(self, run_id: str) -> WorkflowContext:
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                raise KeyError(f"workflow run not found: {run_id}")
            payload = dict(row.input_json or {})
        registry = self.tool_registry
        if registry is None:
            # The snapshot does not store the registry. The engine's registry,
            # when set at construction, is what resume uses. Otherwise the
            # process-wide registry.
            from tools.registry import TOOL_REGISTRY
            registry = TOOL_REGISTRY
        return WorkflowContext.from_snapshot(
            payload,
            tool_registry=registry,
            session_factory=self.session_factory,
        )

    def _workflow_name(self, run_id: str) -> str:
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                raise KeyError(f"workflow run not found: {run_id}")
            return row.workflow_name

    def _step_status(self, run_id: str, step_name: str) -> Optional[str]:
        with self.session_factory() as db:
            row = db.execute(
                select(WorkflowStepRow)
                .where(WorkflowStepRow.run_id == run_id)
                .where(WorkflowStepRow.step_name == step_name)
            ).scalars().first()
            return None if row is None else row.status

    def _current_attempt(self, run_id: str, step_name: str) -> int:
        with self.session_factory() as db:
            row = db.execute(
                select(WorkflowStepRow)
                .where(WorkflowStepRow.run_id == run_id)
                .where(WorkflowStepRow.step_name == step_name)
            ).scalars().first()
            if row is None or row.status == RUN_PENDING:
                return 1
            if row.status == STEP_RETRY:
                return int(row.attempt or 1) + 1
            return int(row.attempt or 1)

    def _outputs(self, run_id: str) -> Dict[str, Dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.execute(
                select(WorkflowStepRow).where(WorkflowStepRow.run_id == run_id)
            ).scalars().all()
            return {row.step_name: dict(row.output_json or {}) for row in rows if row.status == STEP_SUCCESS}

    def _output(self, run_id: str) -> Dict[str, Any]:
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                return {}
            return dict(row.output_json or {})

    def _load_view(self, run_id: str) -> WorkflowRunView:
        with self.session_factory() as db:
            row = db.get(WorkflowRunRow, run_id)
            if row is None:
                raise KeyError(f"workflow run not found: {run_id}")
            return _view(row)


def _view(row: WorkflowRunRow) -> WorkflowRunView:
    return WorkflowRunView(
        run_id=row.id,
        status=row.status,
        workflow_name=row.workflow_name,
        current_step=row.current_step,
        output=dict(row.output_json or {}),
        error=row.error,
        idempotency_key=row.idempotency_key,
    )


def _default_sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)
