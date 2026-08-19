"""Account endpoints: register, login, refresh, me, and handle changes.

These routes are exempt from the auth guard by necessity — they are how a
credential is obtained — so `/me` authenticates itself: it is the one place
a user token is resolved without the middleware's help.
"""

from __future__ import annotations

import asyncio
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_store import DuplicateUser
from .auth_tokens import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    signing_secret,
    verify_password,
)
from . import auth_store
from .auth_guard import bearer_token
from .runtime import handle_error

# Deliberately loose: real validation is the person reading their own inbox.
# This only refuses values that cannot possibly be an address.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Verified against when a login email is unknown, so a wrong email and a
# wrong password take the same time — response timing must not reveal which
# emails hold accounts.
_UNKNOWN_USER_HASH = hash_password("timing-equalizer")


class UserOut(BaseModel):
    id: int
    email: str
    handle: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)
    handle: str


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class RefreshIn(BaseModel):
    refresh_token: str


class HandleIn(BaseModel):
    handle: str


def _validated_handle(handle: str) -> str:
    handle = handle.strip()
    if error := handle_error(handle):
        raise HTTPException(400, error)
    return handle


def _validated_registration(body: RegisterIn) -> tuple[str, str]:
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "that does not look like an email address")
    if len(body.password) < 8:
        raise HTTPException(400, "password must be at least 8 characters")
    return email, _validated_handle(body.handle)


def _issue_tokens(db, user: dict) -> dict:
    secret = signing_secret(db)
    return {
        "access_token": create_access_token(secret, user["id"]),
        "refresh_token": create_refresh_token(secret, user["id"]),
        "user": user,
    }


def _current_user(db, request: Request) -> dict:
    """Resolve the caller's account from its access token, or 401."""
    token = bearer_token(request.headers, request.query_params)
    try:
        user_id = decode_token(signing_secret(db), token, TOKEN_TYPE_ACCESS)
    except TokenError:
        raise HTTPException(401, "authentication required") from None
    user = auth_store.user_by_id(db, user_id)
    if user is None:
        raise HTTPException(401, "authentication required")
    return user


def auth_router(db, on_handle_change=None) -> APIRouter:
    """Build the account routes. ``on_handle_change`` is an async callback
    given the user id after a successful rename — the server uses it to close
    that user's sockets so every tab reconnects under the new handle."""
    router = APIRouter()

    @router.post("/api/auth/register", response_model=TokenResponse, status_code=201)
    async def register(body: RegisterIn):
        email, handle = _validated_registration(body)
        # scrypt is deliberately slow; keep it off the event loop.
        digest = await asyncio.to_thread(hash_password, body.password)
        try:
            user = auth_store.create_user(db, email, handle, digest)
        except DuplicateUser as exc:
            raise HTTPException(409, f"that {exc.field} is already registered") from exc
        return _issue_tokens(db, user)

    @router.post("/api/auth/login", response_model=TokenResponse)
    async def login(body: LoginIn):
        credentials = auth_store.credentials_by_email(db, body.email.strip())
        stored = credentials["password_hash"] if credentials else _UNKNOWN_USER_HASH
        verified = await asyncio.to_thread(verify_password, body.password, stored)
        if credentials is None or not verified:
            raise HTTPException(401, "invalid email or password")
        user = auth_store.user_by_id(db, credentials["id"])
        return _issue_tokens(db, user)

    @router.post("/api/auth/refresh", response_model=TokenResponse)
    async def refresh(body: RefreshIn):
        try:
            user_id = decode_token(
                signing_secret(db), body.refresh_token, TOKEN_TYPE_REFRESH
            )
        except TokenError:
            raise HTTPException(401, "invalid or expired refresh token") from None
        user = auth_store.user_by_id(db, user_id)
        if user is None:
            raise HTTPException(401, "invalid refresh token")
        return _issue_tokens(db, user)

    @router.get("/api/auth/me", response_model=UserOut)
    async def me(request: Request):
        return _current_user(db, request)

    @router.patch("/api/auth/me", response_model=UserOut)
    async def change_handle(request: Request, body: HandleIn):
        user = _current_user(db, request)
        handle = _validated_handle(body.handle)
        try:
            renamed = auth_store.set_handle(db, user["id"], handle)
        except DuplicateUser as exc:
            raise HTTPException(409, "that handle is already registered") from exc
        if on_handle_change is not None:
            await on_handle_change(user["id"])
        return renamed

    return router
