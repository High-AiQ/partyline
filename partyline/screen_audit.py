"""Durable append-only control audit with transactional message publication."""

import hashlib
import json
import time

from .message_queries import as_message


def record(db, share_id, conv_id, agent, entry):
    with db.lock:
        try:
            previous = db.conn.execute(
                "SELECT entry_hash FROM screen_control_audit WHERE share_id=? ORDER BY id DESC LIMIT 1",
                (share_id,),
            ).fetchone()
            prior = previous[0] if previous else ""
            payload = json.dumps([share_id, conv_id, agent, entry, prior], ensure_ascii=False,
                                 separators=(",", ":"))
            digest = hashlib.sha256(payload.encode()).hexdigest()
            db.conn.execute(
                "INSERT INTO screen_control_audit(share_id,conv_id,agent,entry,previous_hash,entry_hash) "
                "VALUES(?,?,?,?,?,?)", (share_id, conv_id, agent, entry, prior, digest))
            db.conn.commit()
        except BaseException:
            db.conn.rollback()
            raise


def _body(rows):
    entries = []
    for row in rows:
        agent, entry = row["agent"], row["entry"]
        if (entries and entries[-1][0] == agent and entries[-1][1].startswith("move (")
                and entries[-1][1].endswith(")") and entries[-1][1].count("(") == 1
                and entry.startswith("move (") and entry.endswith(")") and entry.count("(") == 1):
            entries[-1][1], entries[-1][2] = entry, entries[-1][2] + 1
        else:
            entries.append([agent, entry, 1])
    lines, actor = [], None
    for agent, entry, count in entries:
        text = f"{entry} ×{count}" if count > 1 else entry
        lines.append(f"{agent}: {text}" if agent != actor else text)
        actor = agent
    return "Agent control audit — " + " · ".join(lines) + f" [audit sha256: {rows[-1]['entry_hash']}]"


def publish(db, share_id):
    """Insert the system note and mark its entries together, or leave all pending."""
    with db.lock:
        try:
            rows = db.conn.execute(
                "SELECT * FROM screen_control_audit WHERE share_id=? AND message_id IS NULL ORDER BY id",
                (share_id,),
            ).fetchall()
            if not rows:
                return None
            body, conv_id, now = _body(rows), rows[0]["conv_id"], time.time()
            cursor = db.conn.execute(
                "INSERT INTO messages(conv_id,sender,sender_type,body,created_at) VALUES(?,?,?,?,?)",
                (conv_id, "system", "system", body, now))
            message_id = cursor.lastrowid
            db.conn.execute("UPDATE screen_control_audit SET message_id=? WHERE share_id=? "
                            "AND message_id IS NULL", (message_id, share_id))
            db.conn.commit()
            row = db.conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            return as_message(row)
        except BaseException:
            db.conn.rollback()
            raise


def recover(db):
    """Publish batches left pending by a previous server lifetime."""
    shares = db._exec("SELECT DISTINCT share_id FROM screen_control_audit WHERE message_id IS NULL")
    for row in shares.fetchall():
        publish(db, row["share_id"])
