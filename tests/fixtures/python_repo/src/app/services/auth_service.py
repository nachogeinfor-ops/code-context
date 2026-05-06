"""Authentication service — JWT encoding/decoding and password hashing."""

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.schemas.auth import TokenPayload

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Return the bcrypt hash of *plain_password*."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if *plain_password* matches *hashed_password*."""
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str) -> str:
    """Encode a short-lived JWT access token for *subject* (username)."""
    settings = get_settings()
    expire = datetime.now(tz=UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(subject: str) -> str:
    """Encode a long-lived JWT refresh token for *subject*."""
    settings = get_settings()
    expire = datetime.now(tz=UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_token(token: str, expected_type: str = "access") -> TokenPayload:
    """Decode and validate *token*; raise JWTError on failure."""
    settings = get_settings()
    try:
        raw = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise
    payload = TokenPayload(**raw)
    if payload.type != expected_type:
        raise JWTError(f"Expected token type {expected_type!r}, got {payload.type!r}")
    return payload
