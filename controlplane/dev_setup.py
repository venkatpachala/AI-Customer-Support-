"""Create a missing local session secret without printing or replacing it."""
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key


def ensure_local_secret(path: Path = Path(".env")) -> bool:
    values = dotenv_values(path)
    if (os.getenv("APP_ENV") or values.get("APP_ENV") or "development").lower() == "production":
        raise RuntimeError("Configure production secrets through your deployment secret store")
    if os.getenv("OPS_SESSION_SECRET") or values.get("OPS_SESSION_SECRET"):
        return False
    secret = os.getenv("OPS_PASSWORD") or values.get("OPS_PASSWORD") or secrets.token_urlsafe(48)
    set_key(str(path), "OPS_SESSION_SECRET", secret)
    return True


if __name__ == "__main__":
    created = ensure_local_secret()
    print("Local session secret created in .env." if created else "Local session secret already configured.")
    print("Start or restart the API and worker with the same environment. Secret values are not printed.")
