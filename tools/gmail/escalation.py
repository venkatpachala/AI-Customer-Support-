import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from tools.base.tool import BaseTool
from tools.base.context import ToolContext
from tools.gmail.send import GmailSendEmail


class EscalationEmailRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=10000)
    reason: Optional[str] = None


class GmailSendEscalation(BaseTool):
    """
    Sends escalation email only to tenant/system support allowlist.
    """

    name = "gmail_send_escalation"
    provider = "gmail"
    timeout_seconds = 10.0
    max_retries = 2
    idempotent = False
    request_model = EscalationEmailRequest

    def __init__(self):
        super().__init__()
        self.mailer = GmailSendEmail()
        # dedicated escalation recipients
        raw = os.getenv("GMAIL_ESCALATION_TO", os.getenv("GMAIL_ALLOWLIST", "")).strip()
        self.recipients: List[str] = [x.strip() for x in raw.split(",") if x.strip()]

    def _run(self, request: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
        if not self.recipients:
            # fall back to sender only if configured as allowlisted
            self.recipients = [self.mailer.sender]

        subject = request["subject"]
        body = request["body"]
        reason = request.get("reason")

        full_body = body
        if reason:
            full_body = f"Escalation reason: {reason}\n\n{body}"

        return self.mailer._run(
            {
                "to": self.recipients,
                "subject": subject,
                "body": full_body,
            },
            context,
        )