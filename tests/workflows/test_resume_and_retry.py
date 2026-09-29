"""Resume reloads the same run. Stripe retries stay inside that run."""
import ast
from pathlib import Path

from sqlalchemy import func, select

from db.models import WorkflowRunRow, WorkflowStepRow
from db.session import SessionLocal
from workflows.engine import WorkflowEngine

_ROOT = Path(__file__).resolve().parents[2] / "workflows"
_FORBIDDEN = ("orchestration", "gateway", "fastapi")


def test_resume_continues_the_same_run_after_fetch(world, refund_ctx):
    tools = world["tools"]
    first = world["engine"].start(
        "refund",
        refund_ctx(photos_received=False, amount=500, reason="damaged"),
    )
    assert first.status == "waiting_input"
    assert tools.order_calls == 1
    assert tools.stripe_calls == 0

    # A second engine has none of the first object's memory. It has the database.
    resumed = WorkflowEngine(tool_registry=tools, sleeper=lambda _seconds: None)
    continued = resumed.resume(first.run_id, slots={"photos_received": True})

    assert continued.run_id == first.run_id
    assert continued.status == "succeeded"
    assert continued.output["policy"]["allowed"] is True
    assert tools.order_calls == 1
    assert tools.stripe_calls == 1
    with SessionLocal() as db:
        runs = db.execute(
            select(func.count()).select_from(WorkflowRunRow).where(WorkflowRunRow.case_id == world["case"].case_id)
        ).scalar_one()
        assert runs == 1
        steps = db.execute(
            select(WorkflowStepRow).where(WorkflowStepRow.run_id == first.run_id)
        ).scalars().all()
        assert len(steps) == len({step.step_name for step in steps})
        fetch = next(step for step in steps if step.step_name == "fetch_order")
        assert fetch.status == "success"
        assert fetch.attempt == 1


def test_same_idempotency_key_returns_one_row(world, refund_ctx):
    key = f"{world['tenant_id']}:{world['case'].case_id}:refund:12345"
    ctx = refund_ctx()
    first = world["engine"].start("refund", ctx, idempotency_key=key)
    second = world["engine"].start("refund", ctx, idempotency_key=key)
    assert first.run_id == second.run_id
    assert second.status == "succeeded"
    assert world["tools"].stripe_calls == 1
    with SessionLocal() as db:
        count = db.execute(
            select(func.count()).select_from(WorkflowRunRow).where(WorkflowRunRow.idempotency_key == key)
        ).scalar_one()
        assert count == 1


def test_stripe_failure_retries_then_succeeds_on_the_same_run(world, refund_ctx, monkeypatch):
    monkeypatch.setenv("WORKFLOW_STRIPE_FAIL", "1")
    seen = []

    def sleeper(seconds):
        with SessionLocal() as db:
            row = db.execute(
                select(WorkflowRunRow).where(WorkflowRunRow.case_id == world["case"].case_id)
            ).scalars().one()
            step = db.execute(
                select(WorkflowStepRow)
                .where(WorkflowStepRow.run_id == row.id)
                .where(WorkflowStepRow.step_name == "execute_refund")
            ).scalars().one()
            seen.append({"run": row.status, "attempt": step.attempt, "delay": seconds})
            assert row.status != "succeeded"

    engine = WorkflowEngine(tool_registry=world["tools"], sleeper=sleeper)
    run = engine.start("refund", refund_ctx(amount=500, photos_received=True, reason="damaged"))

    assert run.status == "succeeded"
    assert run.output["policy"]["allowed"] is True
    assert [item["delay"] for item in seen] == [1, 2]
    assert [item["run"] for item in seen] == ["retrying", "retrying"]
    assert world["tools"].stripe_calls == 1
    with SessionLocal() as db:
        step = db.execute(
            select(WorkflowStepRow)
            .where(WorkflowStepRow.run_id == run.run_id)
            .where(WorkflowStepRow.step_name == "execute_refund")
        ).scalars().one()
        assert step.attempt == 3
        assert step.status == "success"
        count = db.execute(
            select(func.count()).select_from(WorkflowRunRow).where(WorkflowRunRow.case_id == world["case"].case_id)
        ).scalar_one()
        assert count == 1


def test_workflow_package_does_not_import_the_graph_or_gateway():
    offenders = []
    for path in _ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in _FORBIDDEN:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []
