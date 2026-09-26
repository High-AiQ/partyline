"""One-use restart approvals issued by a trusted local database operator.

The capability is created outside the attachment fence, which mounts the database
read-only. Only its hash is persisted: reading the database grants no approval.
The token authorizes one pending request on this instance, never machine API access.
"""

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

TTL = 60


class OperatorApproval(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    token: str = Field(min_length=43, max_length=43)


def issue(database: str, request_id: str) -> str:
    """Require an existing writable instance DB; never initialize or migrate it."""
    import re

    if not re.fullmatch(r"[0-9a-f]{12}", request_id):
        raise ValueError("invalid restart request id")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    uri = Path(database).resolve().as_uri() + "?mode=rw"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        with connection:
            connection.execute("DELETE FROM operator_restart_approvals WHERE expires_at < ?",
                               (time.time(),))
            connection.execute(
                "INSERT INTO operator_restart_approvals(request_id,token_hash,expires_at) "
                "VALUES(?,?,?) ON CONFLICT(request_id) DO UPDATE SET "
                "token_hash=excluded.token_hash,expires_at=excluded.expires_at",
                (request_id, digest, time.time() + TTL),
            )
    finally:
        connection.close()
    return token


def consume(db, request_id: str, token: str) -> bool:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return db._exec(
        "DELETE FROM operator_restart_approvals WHERE request_id=? AND token_hash=? "
        "AND expires_at>=? RETURNING request_id", (request_id, digest, time.time()),
    ).fetchone() is not None


def register(app, runtime, approve):
    @app.post("/api/restart-request/operator-approve")
    async def operator_approve(request: Request, body: OperatorApproval):
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            raise HTTPException(403, "local operator approval requires loopback")
        if not consume(runtime.db, body.request_id, body.token):
            raise HTTPException(403, "invalid, expired, or consumed operator approval")
        current = runtime.restart_request
        if current is None or current.id != body.request_id:
            raise HTTPException(404, "that restart request is no longer pending")
        return await approve(current, "local-operator", None)
