"""Who is calling: the gate on every route, and the identity behind it.

Two credential kinds pass this gate. Humans present a JWT access token from
`/api/auth/*`; attached processes present their opaque per-attachment
`api_token` (their PARTYLINE_TOKEN). Either arrives as `Authorization:
Bearer <token>` or, where headers are impossible — WebSocket upgrades from a
browser, `<img>` tags — as a `?token=` query parameter.

Exempt, exactly: the auth endpoints themselves, `/api/version`,
`/api/hooks/*` (guarded by its own per-activation capability token),
`/assets/*`, and `/`. Everything else is 401 without a valid credential.

Sender identity on writes derives from the credential — never from a
client-supplied field — so an authenticated sender cannot be impersonated
and handle collisions cannot occur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse

from . import auth_store
from .auth_tokens import TOKEN_TYPE_ACCESS, TokenError, decode_token, signing_secret

# The browser cannot read the HTTP response of a failed WebSocket upgrade, so
# an unauthenticated socket is accepted and closed with this code instead.
WS_POLICY_VIOLATION = 4401
# Authenticated, but this credential kind has no business on this socket.
WS_FORBIDDEN = 4403

_EXEMPT_PREFIXES = ("/api/auth/", "/api/hooks/", "/assets/")
# /api/restart-plan/failure carries its own capability (the plan's
# report_token) plus a loopback check, exactly like the hooks routes.
_EXEMPT_PATHS = {"/", "/api/version", "/api/restart-plan/failure"}


@dataclass(frozen=True)
class Principal:
    """An authenticated caller: a human account or an attached process."""

    kind: Literal["user", "machine"]
    name: str  # the current handle / attachment name
    user_id: int | None = None


def exempt(path: str) -> bool:
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)


def bearer_token(headers, query_params) -> str:
    scheme, _, credential = (headers.get("authorization") or "").partition(" ")
    if scheme.lower() == "bearer" and credential.strip():
        return credential.strip()
    return (query_params.get("token") or "").strip()


def resolve_principal(db, token: str) -> Principal | None:
    """The identity a token proves, or ``None`` for anything else.

    Machine tokens are opaque random strings, so the database lookup is the
    cheap, always-safe first try; anything it does not know is then treated
    as a JWT access token.
    """
    if not token:
        return None
    attachment = auth_store.attachment_by_api_token(db, token)
    if attachment is not None:
        return Principal(kind="machine", name=attachment["name"])
    try:
        user_id = decode_token(signing_secret(db), token, TOKEN_TYPE_ACCESS)
    except TokenError:
        return None
    user = auth_store.user_by_id(db, user_id)
    if user is None:
        return None
    return Principal(kind="user", name=user["handle"], user_id=user["id"])


def install_auth_guard(app, db) -> None:
    """Require a valid credential on every non-exempt HTTP route."""

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        if not exempt(request.url.path):
            token = bearer_token(request.headers, request.query_params)
            principal = resolve_principal(db, token)
            if principal is None:
                return JSONResponse(
                    {"detail": "authentication required"}, status_code=401
                )
            request.state.principal = principal
        return await call_next(request)


def request_principal(request: Request) -> Principal:
    """The identity the guard attached to this request.

    Missing state means the request reached a protected handler without
    passing the guard — a wiring bug, not a client error — so refusing loudly
    beats inventing an anonymous sender.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "authentication required")
    return principal


async def websocket_principal(db, ws: WebSocket) -> Principal | None:
    """Authenticate a socket, or close it with the 4401 policy code."""
    principal = resolve_principal(db, bearer_token(ws.headers, ws.query_params))
    if principal is None:
        await ws.accept()
        await ws.close(code=WS_POLICY_VIOLATION, reason="authentication required")
    return principal


class UserSocketRegistry:
    """Which open sockets belong to which account, for forced re-auth.

    A handle change closes every socket its user holds — other tabs included
    — with the 4401 code. Each client reconnects, re-authenticates, and comes
    back under the new handle, so no socket anywhere keeps a stale identity.
    """

    def __init__(self):
        self._sockets: dict[int, set[WebSocket]] = {}

    def add(self, user_id: int | None, ws: WebSocket) -> None:
        if user_id is not None:  # machine names never change; don't track them
            self._sockets.setdefault(user_id, set()).add(ws)

    def discard(self, user_id: int | None, ws: WebSocket) -> None:
        if user_id is not None:
            self._sockets.get(user_id, set()).discard(ws)
            if not self._sockets.get(user_id):
                self._sockets.pop(user_id, None)

    async def close_all(self, user_id: int) -> None:
        for ws in list(self._sockets.get(user_id, ())):
            try:
                await ws.close(
                    code=WS_POLICY_VIOLATION, reason="handle changed; reconnect"
                )
            except Exception:
                pass  # a half-open socket cannot be closed cleanly
