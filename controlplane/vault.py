"""Seal connection tokens at rest. The key is the host session secret, never a file in the repo."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from cryptography.fernet import Fernet, MultiFernet, InvalidToken

_PREFIX = "enc:v1:"
_CURRENT = "enc:v2:"


def _cipher() -> MultiFernet:
    keys = [key.strip() for key in os.getenv("CREDENTIAL_ENCRYPTION_KEYS", "").split(",") if key.strip()]
    if not keys:
        from controlplane.settings import production
        secret = os.getenv("OPS_SESSION_SECRET", "")
        if production() or not secret:
            raise ValueError("credential encryption key is not configured")
        keys = [base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()]
    return MultiFernet([Fernet(key.encode()) for key in keys])


def _key() -> bytes:
    secret = (os.getenv("OPS_SESSION_SECRET") or os.getenv("OPS_PASSWORD") or "").strip()
    if not secret:
        raise ValueError("legacy credential decryption secret is not configured")
    return hashlib.sha256(b"d2c-connection-seal|" + secret.encode("utf-8")).digest()


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


def seal(plain: str) -> str:
    return _CURRENT + _cipher().encrypt((plain or "").encode()).decode()


def open_seal(stored: str) -> str:
    text = stored or ""
    if not text:
        return ""
    if text.startswith(_CURRENT):
        try:
            return _cipher().decrypt(text[len(_CURRENT):].encode()).decode()
        except InvalidToken as exc:
            raise ValueError("credential seal failed") from exc
    if not text.startswith(_PREFIX):
        from controlplane.settings import production
        if production():
            raise ValueError("unencrypted credentials must be reconnected")
        return text
    raw = base64.urlsafe_b64decode(text[len(_PREFIX):].encode("ascii"))
    if len(raw) < 48:
        raise ValueError("credential seal is truncated")
    nonce, mac, cipher = raw[:16], raw[16:48], raw[48:]
    key = _key()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("credential seal failed")
    plain = bytes(left ^ right for left, right in zip(cipher, _stream(key, nonce, len(cipher))))
    return plain.decode("utf-8")
