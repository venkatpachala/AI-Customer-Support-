import hashlib
import time
from typing import Optional, Dict, Any, Tuple


class PolicyCache:
    def __init__(self, ttl_seconds: int = 3600, max_items: int = 500):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._store: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def _key(self, tenant_id: str, query: str) -> str:
        norm = " ".join((query or "").lower().split())
        raw = f"{tenant_id}::{norm}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, tenant_id: str, query: str) -> Optional[Dict[str, Any]]:
        key = self._key(tenant_id, query)
        item = self._store.get(key)
        if not item:
            return None
        ts, payload = item
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return payload

    def set(self, tenant_id: str, query: str, payload: Dict[str, Any]) -> None:
        if len(self._store) >= self.max_items:
            # drop oldest
            oldest_key = min(self._store.items(), key=lambda kv: kv[1][0])[0]
            self._store.pop(oldest_key, None)
        key = self._key(tenant_id, query)
        self._store[key] = (time.time(), payload)


policy_cache = PolicyCache()