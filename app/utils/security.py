"""Security utilities: CSRF token generation and validation."""

import hashlib
import hmac
import secrets
import time

from app.config import settings


def generate_csrf_token() -> str:
    """Generate a CSRF token combining a random nonce with a timestamp signature."""
    nonce = secrets.token_hex(16)
    timestamp = str(int(time.time()))
    payload = f"{nonce}:{timestamp}"
    signature = hmac.new(
        settings.secret_key.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{signature}"


def validate_csrf_token(token: str, max_age: int = 3600) -> bool:
    """Validate a CSRF token. Returns True if valid and not expired."""
    try:
        nonce, timestamp, signature = token.rsplit(":", 2)
    except ValueError:
        return False

    payload = f"{nonce}:{timestamp}"
    expected = hmac.new(
        settings.secret_key.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        return False

    try:
        token_time = int(timestamp)
    except ValueError:
        return False

    return (time.time() - token_time) <= max_age
