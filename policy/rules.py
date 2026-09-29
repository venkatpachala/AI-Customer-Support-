"""Small pure helpers. No tenant I/O and no model calls."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

# Low to high. A lower rank never satisfies a higher requirement.
_AUTH_RANK = {
    "anonymous": 0,
    "identified": 1,
    "verified": 2,
}

_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_CURRENCY_RE = re.compile(
    r"(₹|\$|€|£|\binr\b|\brs\.?\b|\busd\b|\beur\b)",
    re.IGNORECASE,
)


def normalize_token(value: Any) -> str:
    """Lowercase identifier. Spaces and hyphens become a single underscore."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = _TOKEN_RE.sub("_", text).strip("_")
    return text


def auth_rank(level: Any) -> int:
    """Rank of a caller. Unknown levels rank below anonymous."""
    return _AUTH_RANK.get(normalize_token(level), -1)


def required_auth_rank(level: Any) -> int:
    """Rank a policy demands. An unknown requirement fails closed."""
    token = normalize_token(level)
    if token not in _AUTH_RANK:
        return 99
    return _AUTH_RANK[token]


def auth_satisfies(actual: Any, required: Any) -> bool:
    """True only when the caller meets or exceeds the required level."""
    return auth_rank(actual) >= required_auth_rank(required)


def parse_amount(value: Any) -> Optional[float]:
    """Major units. Strips currency symbols and thousands separators.

    Booleans and unparseable text become None so a refund cannot treat
    them as zero and slip under the auto cap.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number
    text = str(value).strip()
    if not text:
        return None
    text = _CURRENCY_RE.sub("", text)
    text = text.replace(",", "").replace(" ", "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return float(parsed)


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    token = normalize_token(value)
    return token in {"1", "true", "yes", "y"}


def token_in(value: Optional[str], options: Iterable[str]) -> bool:
    if not value:
        return False
    wanted = normalize_token(value)
    return any(normalize_token(option) == wanted for option in options)


def as_decimal(amount: float) -> Decimal:
    return Decimal(str(amount))


def amount_band(amount: float, auto_max: float, manager_max: float) -> str:
    """auto | manager | above. Caps are inclusive on the upper edge."""
    value = as_decimal(amount)
    auto = as_decimal(auto_max)
    manager = as_decimal(manager_max)
    if value <= auto:
        return "auto"
    if value <= manager:
        return "manager"
    return "above"
