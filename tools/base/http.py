from typing import Any, Dict, Optional
import requests

from tools.base.exceptions import (
    TimeoutError as ToolTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
    AuthenticationError,
    AuthorizationError,
    ResourceNotFoundError,
    ToolError,
)


class HttpClient:
    def __init__(self, default_timeout: float = 10.0):
        self.default_timeout = default_timeout
        self.session = requests.Session()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                headers=headers or {},
                params=params,
                json=json,
                data=data,
                timeout=timeout or self.default_timeout,
            )
        except requests.Timeout as e:
            raise ToolTimeoutError(str(e)) from e
        except requests.ConnectionError as e:
            raise ProviderUnavailableError(str(e)) from e
        except requests.RequestException as e:
            raise ToolError(str(e), code="http_error", retryable=True) from e

        if response.status_code in (401,):
            raise AuthenticationError(f"Unauthorized: {response.text[:200]}")
        if response.status_code in (403,):
            raise AuthorizationError(f"Forbidden: {response.text[:200]}")
        if response.status_code == 404:
            raise ResourceNotFoundError(f"Not found: {response.text[:200]}")
        if response.status_code == 429:
            raise RateLimitError(f"Rate limited: {response.text[:200]}")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"Provider error {response.status_code}: {response.text[:200]}")
        if response.status_code >= 400:
            raise ToolError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                code="http_client_error",
                retryable=False,
            )

        return response