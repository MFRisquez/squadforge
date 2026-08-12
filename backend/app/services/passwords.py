"""Password hashing and reset tokens (stdlib only — keeps the app free/simple)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone


ALGO = "pbkdf2_sha256"
ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), ITERATIONS)
    return f"{ALGO}${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        return False
    # Legacy plaintext PIN support (pre-auth upgrade)
    if "$" not in stored:
        return hmac.compare_digest(stored, password)
    try:
        algo, iters_s, salt, digest_hex = stored.split("$", 3)
        if algo != ALGO:
            return False
        iters = int(iters_s)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iters)
    return hmac.compare_digest(check.hex(), digest_hex)


def new_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reset_expiry(*, hours: int = 2) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
