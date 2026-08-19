"""Password hashing and JWT helpers (access + refresh tokens).

Tokens are stateless HS256 JWTs carrying a `type` claim (`access` or
`refresh`). Access tokens are short-lived; refresh tokens are long-lived and
rotated on use. There is no server-side revocation list (home-lab scale,
single replica). The pattern follows the macros project's auth; the
implementation deliberately does not: PyJWT and stdlib scrypt replace
python-jose and passlib, which both carry known supply-chain problems.

The signing secret is per-instance: minted on first use and persisted in the
instance's own database, so two servers with separate databases can never
accept each other's tokens. There is deliberately no env-var or default-value
fallback — a silent fallback re-creates the failure it prevents.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_LIFETIME = timedelta(minutes=30)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# scrypt cost parameters, recorded in every hash so they can be raised later
# without invalidating existing credentials.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 16384, 8, 1


class TokenError(Exception):
    """The token is missing, malformed, expired, or of the wrong type."""


def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        plain.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            plain.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def signing_secret(db) -> str:
    """This instance's JWT secret, minted on first call and durable after.

    Memoised on the connection so token work after the first call costs no
    write or commit; the cache is per-Db, so tests with several databases
    never cross secrets.
    """
    cached = getattr(db, "_auth_secret", None)
    if cached:
        return cached
    with db.lock:
        db.conn.execute(
            "INSERT OR IGNORE INTO auth_secret(singleton, secret, created_at)"
            " VALUES(1, ?, ?)",
            (secrets.token_hex(32), time.time()),
        )
        db.conn.commit()
        row = db.conn.execute(
            "SELECT secret FROM auth_secret WHERE singleton=1"
        ).fetchone()
    db._auth_secret = row["secret"]
    return db._auth_secret


def create_access_token(secret: str, user_id: int) -> str:
    return _encode(secret, user_id, TOKEN_TYPE_ACCESS, ACCESS_TOKEN_LIFETIME)


def create_refresh_token(secret: str, user_id: int) -> str:
    return _encode(secret, user_id, TOKEN_TYPE_REFRESH, REFRESH_TOKEN_LIFETIME)


def _encode(secret: str, user_id: int, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        # Only the user id: the handle is mutable and is resolved from the
        # database per request, so a handle change never invalidates a token.
        "sub": str(user_id),
        "iat": now,
        "exp": now + lifetime,
        "type": token_type,
        # Timestamps have one-second resolution, so without this two tokens
        # minted in the same second would be byte-identical — and a rotation
        # that hands back the same refresh token is indistinguishable from no
        # rotation at all.
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(secret: str, token: str, expected_type: str) -> int:
    """Validate a token of the expected type and return its user id."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token")
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("token has no usable subject") from exc
