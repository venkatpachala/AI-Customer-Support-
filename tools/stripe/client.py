from typing import Any, Dict, Optional
from tools.base.http import HttpClient
from tools.base.context import ToolContext
from tools.stripe.auth import get_stripe_auth, get_stripe_base_url


class StripeClient:
    def __init__(self, timeout_seconds: float = 15.0):
        self.http = HttpClient(default_timeout=timeout_seconds)
        self.auth = get_stripe_auth()
        self.base_url = get_stripe_base_url()

    def _headers(
        self,
        context: ToolContext,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        headers = self.auth.apply(headers, context)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def get(
        self,
        path: str,
        context: ToolContext,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self.http.request(
            "GET",
            url,
            headers=self._headers(context),
            params=params,
            timeout=timeout,
        )
        return response.json()

    def post_form(
        self,
        path: str,
        context: ToolContext,
        form_data: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self.http.request(
            "POST",
            url,
            headers=self._headers(context, idempotency_key=idempotency_key),
            data=form_data,
            timeout=timeout,
        )
        return response.json()