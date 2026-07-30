from typing import Any, Dict, Optional
from tools.base.http import HttpClient
from tools.base.context import ToolContext
from tools.shopify.auth import get_shopify_auth, get_shopify_base_url


class ShopifyClient:
    def __init__(self, timeout_seconds: float = 10.0):
        self.http = HttpClient(default_timeout=timeout_seconds)
        self.auth = get_shopify_auth()
        self.base_url = get_shopify_base_url()

    def _headers(self, context: ToolContext) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return self.auth.apply(headers, context)

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