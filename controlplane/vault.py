"""Seal connection tokens at rest. The key is the host session secret, never a file in the repo."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

_PREFIX = "enc:v1:"


def _key() -> bytes:
    secret = (os.getenv("OPS_SESSION_SECRET") or os.getenv("OPS_PASSWORD") or "").strip()
    if not secret:
        secret = "local-dev-seal"
    return hashlib.sha256(b"d2c-connection-seal|" + secret.encode("utf-8")).digest()


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


def seal(plain: str) -> str:
    data = (plain or "").encode("utf-8")
    key = _key()
    nonce = os.urandom(16)
    cipher = bytes(left ^ right for left, right in zip(data, _stream(key, nonce, len(data))))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    blob = base64.urlsafe_b64encode(nonce + mac + cipher).decode("ascii")
    return _PREFIX + blob


def open_seal(stored: str) -> str:
    text = stored or ""
    if not text:
        return ""
    if not text.startswith(_PREFIX):
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
