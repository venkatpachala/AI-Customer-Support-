from typing import Any, Dict, Optional
from tools.base.http import HttpClient
from tools.base.context import ToolContext
from tools.gmail.auth import GmailOAuth2Auth


class GmailClient:
    def __init__(self, timeout_seconds: float = 10.0):
        self.http = HttpClient(default_timeout=timeout_seconds)
        self.auth = GmailOAuth2Auth()
        self.base_url = "https://gmail.googleapis.com/gmail/v1"

    def _headers(self, context: ToolContext) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return self.auth.apply(headers, context)

    def post(
        self,
        path: str,
        context: ToolContext,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self.http.request(
            "POST",
            url,
            headers=self._headers(context),
            json=json,
            timeout=timeout,
        )
        return response.json()