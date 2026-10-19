"""Explicit currency boundary. Internal policy limits remain in major units."""
from decimal import Decimal, InvalidOperation


def to_minor(value: object, currency: str = "inr") -> int:
    if currency.lower() not in {"inr", "usd", "eur", "gbp"}:
        raise ValueError("unsupported currency")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    if not amount.is_finite() or amount <= 0 or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("amount must be positive with at most two decimal places")
    return int(amount * 100)
