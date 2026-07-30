import os
from tools.base.auth import BearerTokenAuth


def get_stripe_auth() -> BearerTokenAuth:
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    return BearerTokenAuth(token=secret)


def get_stripe_base_url() -> str:
    return os.getenv("STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")