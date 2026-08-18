"""Path-glob write claims — the lock that prose ownership never was.

Two agents on one checkout collided today because ownership lived only in
chat. A claim is durable, line-scoped, and refused with the conflicting
holder rather than silently overlapping.
"""

from __future__ import annotations

import fnmatch
import json
import time
import uuid

from pydantic import BaseModel, Field

TTL_SECONDS = 4 * 3600
MAX_PATHS = 32
MAX_PATH_LEN = 240

CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS claims(
  id TEXT PRIMARY KEY,
  conv_id TEXT NOT NULL,
  owner TEXT NOT NULL,
  paths TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_conv ON claims(conv_id, expires_at);
"""


class Claim(BaseModel):
    id: str
    owner: str
    paths: list[str]
    created_at: float
    expires_at: float


class ClaimIn(BaseModel):
    owner: str
    paths: list[str] = Field(min_length=1, max_length=MAX_PATHS)


class ClaimConflict(BaseModel):
    detail: str
    conflict: Claim


def ensure_schema(db) -> None:
    with db.lock:
        db.conn.executescript(CLAIMS_DDL)
        db.conn.commit()


def expire(db, now: float | None = None) -> None:
    ensure_schema(db)
    db._exec("DELETE FROM claims WHERE expires_at<=?", (now if now is not None else time.time(),))


def _row(row) -> Claim:
    return Claim(
        id=row["id"],
        owner=row["owner"],
        paths=json.loads(row["paths"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def overlaps(left: list[str], right: list[str]) -> bool:
    """True when any pair of globs could name the same path."""
    for first in left:
        for second in right:
            if (
                first == second
                or fnmatch.fnmatch(first, second)
                or fnmatch.fnmatch(second, first)
            ):
                return True
    return False


def clean_paths(raw: list[str]) -> list[str]:
    paths = []
    for item in raw:
        text = item.strip().replace("\\", "/")
        if not text or text.startswith("/") or ".." in text.split("/"):
            raise ValueError(f"unsafe claim path: {item!r}")
        if len(text) > MAX_PATH_LEN:
            raise ValueError(f"claim path exceeds {MAX_PATH_LEN} characters")
        if text not in paths:
            paths.append(text)
    if not paths:
        raise ValueError("at least one path is required")
    return paths


def list_claims(db, conv_id: str) -> list[Claim]:
    expire(db)
    rows = db._exec(
        "SELECT * FROM claims WHERE conv_id=? ORDER BY created_at", (conv_id,)
    ).fetchall()
    return [_row(row) for row in rows]


def get_claim(db, claim_id: str) -> Claim | None:
    expire(db)
    row = db._exec("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    return _row(row) if row else None


def conflict_for(db, conv_id: str, owner: str, paths: list[str]) -> Claim | None:
    for existing in list_claims(db, conv_id):
        if existing.owner == owner:
            continue
        if overlaps(existing.paths, paths):
            return existing
    return None


def create_claim(db, conv_id: str, owner: str, paths: list[str]) -> Claim:
    """Insert or refresh this owner's claim. Raises ValueError or returns conflict via ClaimConflict."""
    expire(db)
    owner = owner.strip()
    if not owner:
        raise ValueError("owner is required")
    paths = clean_paths(paths)
    if found := conflict_for(db, conv_id, owner, paths):
        raise ClaimTaken(found)
    now = time.time()
    existing = [
        claim for claim in list_claims(db, conv_id) if claim.owner == owner
    ]
    if existing:
        claim = existing[0]
        merged = clean_paths([*claim.paths, *paths])
        db._exec(
            "UPDATE claims SET paths=?, expires_at=? WHERE id=?",
            (json.dumps(merged), now + TTL_SECONDS, claim.id),
        )
        return get_claim(db, claim.id)
    ident = str(uuid.uuid4())
    db._exec(
        "INSERT INTO claims(id,conv_id,owner,paths,created_at,expires_at) VALUES(?,?,?,?,?,?)",
        (ident, conv_id, owner, json.dumps(paths), now, now + TTL_SECONDS),
    )
    return get_claim(db, ident)


def release_claim(db, claim_id: str, owner: str | None = None) -> bool:
    expire(db)
    claim = get_claim(db, claim_id)
    if claim is None:
        return False
    if owner is not None and claim.owner != owner:
        raise PermissionError(claim.owner)
    db._exec("DELETE FROM claims WHERE id=?", (claim_id,))
    return True


def purge_claims(db, conv_id: str) -> None:
    ensure_schema(db)
    db._exec("DELETE FROM claims WHERE conv_id=?", (conv_id,))


class ClaimTaken(Exception):
    def __init__(self, conflict: Claim):
        super().__init__(f"already claimed by {conflict.owner}")
        self.conflict = conflict
