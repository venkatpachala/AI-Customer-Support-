"""Customer-visible copy. Success language follows workflow_status only."""
from __future__ import annotations

import re

_COMPLETED = re.compile(
    r"refund (has been |was )?completed|refund completed|refund has been issued|"
    r"your refund (is|was) complete|we have issued (the |your )?refund",
    re.IGNORECASE,
)


def scrub_reply(text: str | None, workflow_status: str | None) -> str:
    body = text or ""
    if workflow_status == "succeeded":
        return body
    return _COMPLETED.sub("the refund is not complete", body)


def waiting_copy(workflow_status: str | None) -> str | None:
    if workflow_status == "waiting_approval":
        return "Waiting for approval"
    if workflow_status == "succeeded":
        return "Refund succeeded"
    return None
