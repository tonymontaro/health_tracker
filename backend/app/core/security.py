import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str, settings: Settings) -> str:
    key = settings.session_secret.get_secret_value().encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def session_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.session_days)
