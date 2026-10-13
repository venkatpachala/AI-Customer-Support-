"""Log which prompt template ran. Filled customer text stays out of this line."""
from __future__ import annotations

from observability.logging import log_event


def log_prompt_template(name: str, request_id: str, *, node: str = "planner") -> None:
    log_event(
        "prompt_template",
        request_id,
        node=node,
        data={"template": name},
    )
