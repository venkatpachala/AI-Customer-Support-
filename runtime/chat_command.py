"""Transport-independent chat input; adapters supply verified session context."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass
class ChatCommand:
    body: dict[str, Any]
    session_id: str
    request_id: str = ""
    client_host: str = "unknown"
    idempotency_key: str = ""
    state: SimpleNamespace = field(init=False)

    def __post_init__(self) -> None:
        self.state = SimpleNamespace(request_id=self.request_id)

    @property
    def cookies(self) -> dict[str, str]:
        return {"d2c_session": self.session_id}

    @property
    def client(self) -> SimpleNamespace:
        return SimpleNamespace(host=self.client_host)

    async def json(self) -> dict[str, Any]:
        return dict(self.body)
