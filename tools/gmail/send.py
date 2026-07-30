import base64
import os
import re
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from tools.base.tool import BaseTool
from tools.base.context import ToolContext
from tools.base.rate_limit import TokenBucketRateLimiter
from tools.base.retry import RetryPolicy
from tools.base.exceptions import ValidationError, AuthorizationError
from tools.gmail.client import GmailClient


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SendEmailRequest(BaseModel):
    to: List[str] = Field(..., min_items=1)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=10000)
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None

    @validator("to", "cc", "bcc", pre=True, each_item=True)
    def validate_email(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if not EMAIL_REGEX.match(v):
            raise ValueError(f"Invalid email: {v}")
        return v


def _default_allowlist() -> List[str]:
    """
    Comma-separated allowlist from env.
    Example: support@company.com,escalations@company.com
    """
    raw = os.getenv("GMAIL_ALLOWLIST", "").strip()
    if not raw:
        sender = os.getenv("GMAIL_SENDER", "").strip()
        return [sender] if sender else []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _build_raw_message(
    *,
    sender: str,
    to: List[str],
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
) -> str:
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = ", ".join(to)
    msg["from"] = sender
    msg["subject"] = subject
    if cc:
        msg["cc"] = ", ".join(cc)
    if bcc:
        msg["bcc"] = ", ".join(bcc)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


class GmailSendEmail(BaseTool):
    """
    Send an email through Gmail API.

    Safety:
    - recipient allowlist enforced
    - sender fixed from env
    - body/subject length validated
    """

    name = "gmail_send_email"
    provider = "gmail"
    timeout_seconds = 10.0
    max_retries = 2
    idempotent = False
    request_model = SendEmailRequest

    def __init__(self, allowlist: Optional[List[str]] = None):
        super().__init__(
            rate_limiter=TokenBucketRateLimiter(rate_per_sec=1, burst=3),
            retry_policy=RetryPolicy(max_retries=self.max_retries),
        )
        self.client = GmailClient(timeout_seconds=self.timeout_seconds)
        self.sender = os.getenv("GMAIL_SENDER", "").strip()
        if not self.sender:
            raise RuntimeError("GMAIL_SENDER is not set")
        self.allowlist = set(x.lower() for x in (allowlist or _default_allowlist()))

    def _assert_allowlisted(self, emails: List[str]):
        if not self.allowlist:
            raise AuthorizationError("Gmail allowlist is empty; refusing to send")

        for email in emails:
            if email.lower() not in self.allowlist:
                raise AuthorizationError(f"Recipient not allowlisted: {email}")

    def _run(self, request: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
        to = request["to"]
        cc = request.get("cc") or []
        bcc = request.get("bcc") or []
        subject = request["subject"]
        body = request["body"]

        all_recipients = list(to) + list(cc) + list(bcc)
        self._assert_allowlisted(all_recipients)

        # Optional audit footer
        body_with_meta = (
            f"{body}\n\n"
            f"---\n"
            f"request_id={context.request_id}\n"
            f"tenant_id={context.tenant_id}\n"
            f"case_id={context.case_id or '-'}\n"
            f"customer_id={context.customer_id or '-'}\n"
        )

        raw = _build_raw_message(
            sender=self.sender,
            to=to,
            subject=subject,
            body=body_with_meta,
            cc=cc or None,
            bcc=bcc or None,
        )

        data = self.client.post(
            "/users/me/messages/send",
            context=context,
            json={"raw": raw},
            timeout=self.timeout_seconds,
        )

        return {
            "message_id": data.get("id"),
            "thread_id": data.get("threadId"),
            "label_ids": data.get("labelIds", []),
            "to": to,
            "subject": subject,
            "sender": self.sender,
            "status": "sent",
        }