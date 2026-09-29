"""Named workflows the engine can start."""
from __future__ import annotations

from typing import Dict

from workflows.definitions.cancel import CANCEL
from workflows.definitions.order_status import ORDER_STATUS
from workflows.definitions.refund import REFUND, WorkflowDefinition
from workflows.definitions.return_damaged import RETURN_DAMAGED


def build_registry() -> Dict[str, WorkflowDefinition]:
    definitions = (REFUND, RETURN_DAMAGED, CANCEL, ORDER_STATUS)
    return {item.name: item for item in definitions}


WORKFLOWS = build_registry()


def get_workflow(name: str) -> WorkflowDefinition:
    key = (name or "").strip()
    try:
        return WORKFLOWS[key]
    except KeyError as exc:
        known = ", ".join(sorted(WORKFLOWS))
        raise KeyError(f"Unknown workflow '{name}'. Known: {known}") from exc
