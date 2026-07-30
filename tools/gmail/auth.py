import os
import time
import threading
from typing import Dict, Optional

import requests

from tools.base.context import ToolContext
from tools.base.exceptions import AuthenticationError


class GmailOAuth2Auth:
    """
    OAuth2 auth using refresh token.
    Caches access token in-memory until near expiry.
    """

    def __init__(self):
        self.client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
        self.refresh_token = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
        self.token_uri = os.getenv("GMAIL_TOKEN_URI", "https://oauth2.googleapis.com/token").strip()

        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise RuntimeError("Gmail OAuth env vars are missing")

        self._access_token: Optional[str] = None
        self._expires_at: float = 0
        self._lock = threading.Lock()

    def _refresh(self) -> str:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            resp = requests.post(self.token_uri, data=data, timeout=10)
        except requests.RequestException as e:
            raise AuthenticationError(f"Gmail token refresh failed: {e}") from e

        if resp.status_code >= 400:
            raise AuthenticationError(f"Gmail token refresh error: {resp.text[:200]}")

        payload = resp.json()
        access_token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))

        if not access_token:
            raise AuthenticationError("Gmail access_token missing in refresh response")

        # refresh 60s early
        self._access_token = access_token
        self._expires_at = time.time() + max(60, expires_in - 60)
        return access_token

    def get_access_token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at:
                return self._access_token
            return self._refresh()

    def apply(self, headers: Dict[str, str], context: ToolContext) -> Dict[str, str]:
        token = self.get_access_token()
        headers = dict(headers)
        headers["Authorization"] = f"Bearer {token}"
        return headers