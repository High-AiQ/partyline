"""User accounts and per-attachment machine credentials, over the shared Db.

Handles live in the same mention namespace as attachment names, so both
uniqueness checks here are case-insensitive, exactly like mention routing.
"""

from __future__ import annotations

import secrets
import sqlite3
import time


class DuplicateUser(Exception):
    """The email or handle is already registered."""

    def __init__(self, field: str):
        self.field = field  # "email" | "handle"
        super().__init__(f"{field} is already registered")


def _public(row) -> dict:
    return {"id": row["id"], "email": row["email"], "handle": row["handle"]}


def _duplicate_field(exc: sqlite3.IntegrityError) -> str:
    return "email" if "email" in str(exc).lower() else "handle"


def _attachment_owns_handle(conn, handle: str) -> bool:
    """Whether any attachment row — live or resumable — has this name.

    Checked under the same lock as the user write: users and attachments
    share the mention namespace, and the attach route checks the users table,
    so without this the no-collision guarantee would be order-dependent.
    """
    return conn.execute(
        "SELECT 1 FROM attachments WHERE lower(name)=?", (handle.lower(),)
    ).fetchone() is not None


def create_user(db, email: str, handle: str, password_hash: str) -> dict:
    with db.lock:
        if _attachment_owns_handle(db.conn, handle):
            raise DuplicateUser("handle")
        try:
            cur = db.conn.execute(
                "INSERT INTO users(email, handle, password_hash, created_at)"
                " VALUES(?,?,?,?)",
                (email.lower(), handle, password_hash, time.time()),
            )
            db.conn.commit()
        except sqlite3.IntegrityError as exc:
            db.conn.rollback()
            raise DuplicateUser(_duplicate_field(exc)) from exc
    user = user_by_id(db, cur.lastrowid)
    assert user is not None  # a committed INSERT is immediately readable
    return user


def credentials_by_email(db, email: str) -> dict | None:
    """The full user row, hash included — for login verification only."""
    with db.lock:
        row = db.conn.execute(
            "SELECT * FROM users WHERE lower(email)=?", (email.lower(),)
        ).fetchone()
    return dict(row) if row else None


def user_by_id(db, user_id: int) -> dict | None:
    with db.lock:
        row = db.conn.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return _public(row) if row else None


def handle_taken(db, handle: str) -> bool:
    with db.lock:
        row = db.conn.execute(
            "SELECT 1 FROM users WHERE lower(handle)=?", (handle.lower(),)
        ).fetchone()
    return row is not None


def set_handle(db, user_id: int, handle: str) -> dict | None:
    """Rename a user, or raise ``DuplicateUser`` when the handle is taken.

    Re-casing your own handle is allowed: the case-insensitive unique index
    is per row, so a row updating itself can never collide with itself.
    """
    with db.lock:
        if _attachment_owns_handle(db.conn, handle):
            raise DuplicateUser("handle")
        try:
            db.conn.execute(
                "UPDATE users SET handle=? WHERE id=?", (handle, user_id)
            )
            db.conn.commit()
        except sqlite3.IntegrityError as exc:
            db.conn.rollback()
            raise DuplicateUser("handle") from exc
    return user_by_id(db, user_id)


# -- attachment machine tokens ----------------------------------------------
def ensure_api_token(db, att_id: str) -> str:
    """Mint the attachment's stable machine credential, once.

    The token survives activations and resumes on purpose: a resumed process
    is handed the same PARTYLINE_TOKEN its briefing already told it about.
    """
    with db.lock:
        db.conn.execute(
            "UPDATE attachments SET api_token=? WHERE id=? AND api_token IS NULL",
            (secrets.token_urlsafe(32), att_id),
        )
        db.conn.commit()
        row = db.conn.execute(
            "SELECT api_token FROM attachments WHERE id=?", (att_id,)
        ).fetchone()
    if row is None:
        raise KeyError(f"no attachment {att_id}")
    return row["api_token"]


def attachment_by_api_token(db, token: str) -> dict | None:
    with db.lock:
        row = db.conn.execute(
            "SELECT * FROM attachments WHERE api_token=?", (token,)
        ).fetchone()
    return dict(row) if row else None
