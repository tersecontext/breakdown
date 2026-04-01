import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "jti": str(session_id),
        "role": role,
        "exp": now + timedelta(seconds=settings.access_token_ttl),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises jwt.PyJWTError subclasses on failure."""
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub", "jti"]},
    )


def generate_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex_hash). Store only the hash."""
    raw = secrets.token_hex(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_refresh_token(raw: str) -> str:
    """SHA-256 hash a raw refresh token for DB lookup. Counterpart to generate_refresh_token."""
    return hashlib.sha256(raw.encode()).hexdigest()
