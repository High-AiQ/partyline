"""Stopped-roster persistence: fresh identities and irreversible record removal."""

import json
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import _att_row


MAX_REFRESH_MESSAGES = 100
MAX_REFRESH_CONTEXT_CHARS = 32_000


class FreshAttachmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint: str = Field(default="", max_length=8000)
    after_message_id: int | None = Field(default=None, ge=1, le=2**63 - 1, strict=True)

    @model_validator(mode="after")
    def boundary_requires_checkpoint(self):
        self.checkpoint = self.checkpoint.strip()
        if self.after_message_id is not None and not self.checkpoint:
            raise ValueError("a replay boundary requires a checkpoint")
        return self


def require_stopped(db, att_id):
    return _require_stopped(db.get_attachment(att_id))


def _require_stopped(att):
    if att is None:
        raise HTTPException(404, "attachment not found")
    if att["status"] not in ("exited", "detached"):
        raise HTTPException(409, "detach the process before starting fresh or removing it")
    return att


async def create_fresh_record(db, expected, body):
    """Reserve the handle before awaiting spawn; leave the old session on failure."""
    async with db._runtime_serialized_async():
        with db.lock, db.conn:
            row = db.conn.execute("SELECT * FROM attachments WHERE id=?", (expected["id"],)).fetchone()
            att = _require_stopped(_att_row(row) if row else None)
            if any(att[key] != expected[key] for key in ("command", "adapter", "cwd")):
                raise HTTPException(409, "attachment settings changed; refresh and try again")
            conv = db.conn.execute("SELECT * FROM conversations WHERE id=?", (att["conv_id"],)).fetchone()
            if conv["archived_at"] is not None:
                raise HTTPException(409, "restore the line before starting fresh")
            if db.conn.execute(
                "SELECT 1 FROM attachments WHERE conv_id=? AND lower(name)=lower(?) "
                "AND status IN ('starting','running')", (att["conv_id"], att["name"])
            ).fetchone():
                raise HTTPException(409, "this handle already has a live process")
            latest = db.conn.execute(
                "SELECT COALESCE(MAX(id),0) FROM messages WHERE conv_id=?",
                (att["conv_id"],),
            ).fetchone()[0]
            cursor = latest if body.after_message_id is None else body.after_message_id
            if cursor and not db.conn.execute(
                "SELECT 1 FROM messages WHERE conv_id=? AND id=?", (att["conv_id"], cursor)
            ).fetchone():
                raise HTTPException(400, "checkpoint message must belong to this line")
            if body.after_message_id is not None:
                count, characters = db.conn.execute(
                    "SELECT COUNT(*),COALESCE(SUM(LENGTH(body)),0) FROM messages "
                    "WHERE conv_id=? AND id>? AND sender!=?",
                    (att["conv_id"], cursor, att["name"]),
                ).fetchone()
                require_bounded_replay(count, characters)
            ident, owner = str(uuid.uuid4()), str(uuid.uuid4())
            db.conn.execute(
                "INSERT INTO attachments(id,conv_id,name,adapter,command,cwd,status,"
                "runtime_owner,last_seen,created_at) VALUES(?,?,?,?,?,?,'starting',?,?,?)",
                (ident, att["conv_id"], att["name"], att["adapter"], json.dumps(att["command"]),
                 att["cwd"], owner, cursor, time.time()),
            )
        return db.get_attachment(ident)


async def remove_stopped_record(db, att_id, *, missing_ok=False):
    """Forget credentials/delivery state while preserving conversation messages."""
    async with db._runtime_serialized_async():
        with db.lock, db.conn:
            row = db.conn.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone()
            if row is None and missing_ok:
                return None
            att = _require_stopped(_att_row(row) if row else None)
            for table in ("queued_delivery_messages", "transcript_delivery_records"):
                db.conn.execute(f"DELETE FROM {table} WHERE attachment_id=?", (att_id,))
            db.conn.execute("DELETE FROM attachments WHERE id=?", (att_id,))
            plan = db.conn.execute("SELECT attachment_ids FROM restart_plan WHERE singleton=1").fetchone()
            if plan:
                remaining = [ident for ident in json.loads(plan[0]) if ident != att_id]
                if remaining:
                    db.conn.execute("UPDATE restart_plan SET attachment_ids=? WHERE singleton=1",
                                    (json.dumps(remaining),))
                else:
                    db.conn.execute("DELETE FROM restart_plan WHERE singleton=1")
        return att


def require_bounded_replay(message_count: int, character_count: int) -> None:
    """Refuse stale checkpoints instead of silently omitting instructions."""
    if message_count > MAX_REFRESH_MESSAGES or character_count > MAX_REFRESH_CONTEXT_CHARS:
        raise HTTPException(
            400, f"checkpoint would replay {message_count} messages ({character_count} characters); "
            f"limit is {MAX_REFRESH_MESSAGES} messages and {MAX_REFRESH_CONTEXT_CHARS} characters. "
            "Use a newer checkpoint, or leave both fields blank for a clean start.",
        )
