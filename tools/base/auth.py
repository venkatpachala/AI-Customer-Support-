from typing import Dict, Protocol
from tools.base.context import ToolContext


class AuthStrategy(Protocol):
    def apply(self, headers: Dict[str, str], context: ToolContext) -> Dict[str, str]:
        ...


class NoAuth:
    def apply(self, headers: Dict[str, str], context: ToolContext) -> Dict[str, str]:
        return headers


class ApiKeyAuth:
    """
    Generic API key header auth.
    Example: Shopify X-Shopify-Access-Token
    """

    def __init__(self, header_name: str, api_key: str):
        self.header_name = header_name
        self.api_key = api_key

    def apply(self, headers: Dict[str, str], context: ToolContext) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError("API key is missing")
        headers = dict(headers)
        headers[self.header_name] = self.api_key
        return headers


class BearerTokenAuth:
    def __init__(self, token: str):
        self.token = token

    def apply(self, headers: Dict[str, str], context: ToolContext) -> Dict[str, str]:
        if not self.token:
            raise ValueError("Bearer token is missing")
        headers = dict(headers)
        headers["Authorization"] = f"Bearer {self.token}"
        return headers