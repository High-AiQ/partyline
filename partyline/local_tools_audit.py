"""Durable hash-chained audit of every local-tool script, with transactional chat-note publication."""

import hashlib
import json
import time

from .message_queries import as_message

MAX_CODE = 65536


def first_line(code: str, width: int = 60) -> str:
    line = next((item.strip() for item in code.splitlines() if item.strip()), "")
    return line[:width] + ("…" if len(line) > width else "")


def record(db, session_id, conv_id, agent, kind, op, entry, code=None):
    """Append one row: kind is call (before sending), result (the outcome) or event (grant, revoke)."""
    sha = hashlib.sha256(code.encode()).hexdigest() if code is not None else None
    with db.lock:
        try:
            previous = db.conn.execute(
                "SELECT entry_hash FROM local_tool_audit WHERE session_id=? ORDER BY id DESC LIMIT 1",
                (session_id,)).fetchone()
            prior = previous[0] if previous else ""
            payload = json.dumps([session_id, conv_id, agent, kind, op, entry, sha, prior],
                                 ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(payload.encode()).hexdigest()
            db.conn.execute(
                "INSERT INTO local_tool_audit(session_id,conv_id,agent,kind,op,entry,code,code_sha,"
                "previous_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (session_id, conv_id, agent, kind, op, entry, code[:MAX_CODE] if code else code, sha,
                 prior, digest))
            db.conn.commit()
        except BaseException:
            db.conn.rollback()
            raise


def rows(db, session_id):
    return [dict(row) for row in db._exec(
        "SELECT * FROM local_tool_audit WHERE session_id=? ORDER BY id", (session_id,)).fetchall()]


def _body(pending):
    parts = [f"{row['agent']}: {row['entry']}" for row in pending]
    return "Local tools audit — " + " · ".join(parts) + f" [audit sha256: {pending[-1]['entry_hash']}]"


def publish(db, session_id):
    """Insert the system note and mark its rows together, or leave all pending."""
    with db.lock:
        try:
            pending = db.conn.execute(
                "SELECT * FROM local_tool_audit WHERE session_id=? AND message_id IS NULL ORDER BY id",
                (session_id,)).fetchall()
            if not pending:
                return None
            cursor = db.conn.execute(
                "INSERT INTO messages(conv_id,sender,sender_type,body,created_at) VALUES(?,?,?,?,?)",
                (pending[0]["conv_id"], "system", "system", _body(pending), time.time()))
            message_id = cursor.lastrowid
            db.conn.execute("UPDATE local_tool_audit SET message_id=? WHERE session_id=? "
                            "AND message_id IS NULL", (message_id, session_id))
            db.conn.commit()
            return as_message(db.conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone())
        except BaseException:
            db.conn.rollback()
            raise


def recover(db):
    """Publish batches left pending by a previous server lifetime."""
    pending = db._exec("SELECT DISTINCT session_id FROM local_tool_audit WHERE message_id IS NULL")
    for row in pending.fetchall():
        publish(db, row["session_id"])
