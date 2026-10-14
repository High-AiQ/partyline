"""Line-bridge rows: who is bridged to whom, and the audit log of what crossed.

A bridge is two sides, ``a`` and ``b``, each a line and its one ambassador.
The store is pure database; opening, closing and delivery live in
`bridge_service` and `bridge_delivery`.
"""

import time
import uuid

from .hierarchy import ancestors

LIVE = ("starting", "running")
WINDOW_SECONDS = 600
WINDOW_LIMIT = 30


def tree_root(db, conv_id: str) -> str:
    lineage = ancestors(db, conv_id)
    return lineage[-1] if lineage else conv_id


def get_bridge(db, bridge_id: str) -> dict | None:
    row = db._exec("SELECT * FROM line_bridges WHERE id=?", (bridge_id,)).fetchone()
    return dict(row) if row else None


def open_bridge_for_line(db, conv_id: str) -> dict | None:
    row = db._exec(
        "SELECT * FROM line_bridges WHERE closed_at IS NULL"
        " AND (a_conv_id=? OR b_conv_id=?) ORDER BY opened_at DESC",
        (conv_id, conv_id),
    ).fetchone()
    return dict(row) if row else None


def open_bridge_for_attachment(db, att_id: str) -> dict | None:
    row = db._exec(
        "SELECT * FROM line_bridges WHERE closed_at IS NULL"
        " AND (a_attachment_id=? OR b_attachment_id=?)",
        (att_id, att_id),
    ).fetchone()
    return dict(row) if row else None


def open_bridges(db) -> list[dict]:
    return [dict(r) for r in db._exec(
        "SELECT * FROM line_bridges WHERE closed_at IS NULL").fetchall()]


def side(bridge: dict, att_id: str) -> tuple[str, str] | None:
    """(this side's key, the other side's key) for an ambassador, else None."""
    if bridge["a_attachment_id"] == att_id:
        return "a", "b"
    if bridge["b_attachment_id"] == att_id:
        return "b", "a"
    return None


def bridged_across(db, conv_id: str, parent_id: str) -> bool:
    """True when linking ``conv_id`` under ``parent_id`` joins the two ends of an open bridge."""
    from .hierarchy import subtree_conversation_ids

    moving = set(subtree_conversation_ids(db, conv_id))
    target = set(subtree_conversation_ids(db, tree_root(db, parent_id)))
    return any(
        (b["a_conv_id"] in moving and b["b_conv_id"] in target)
        or (b["b_conv_id"] in moving and b["a_conv_id"] in target)
        for b in open_bridges(db)
    )


def lines_of(bridge: dict) -> tuple[str, str]:
    return bridge["a_conv_id"], bridge["b_conv_id"]


def refusal(db, a: dict, b: dict) -> str | None:
    """Why this pair cannot be bridged, or None. Each side is {conv_id, attachment_id}."""
    if a["conv_id"] == b["conv_id"]:
        return "a bridge needs two different lines"
    for end in (a, b):
        line = db.get_conversation(end["conv_id"])
        if line is None:
            return "unknown line"
        if line["archived_at"]:
            return f"line «{line['name']}» is archived"
        att = db.get_attachment(end["attachment_id"])
        if att is None or att["conv_id"] != end["conv_id"] or att["status"] not in LIVE:
            return f"the ambassador is not live on «{line['name']}»"
    if tree_root(db, a["conv_id"]) == tree_root(db, b["conv_id"]):
        return "both lines are in one tree — they already reach each other through the hierarchy"
    for end in (a, b):
        if open_bridge_for_line(db, end["conv_id"]) is not None:
            name = db.get_conversation(end["conv_id"])["name"]
            return f"line «{name}» already has an open bridge"
    return None


def create(db, a: dict, b: dict, opened_by: str) -> dict:
    bridge_id = str(uuid.uuid4())
    db._exec(
        "INSERT INTO line_bridges(id,a_conv_id,a_attachment_id,b_conv_id,b_attachment_id,"
        "opened_at,opened_by) VALUES(?,?,?,?,?,?,?)",
        (bridge_id, a["conv_id"], a["attachment_id"], b["conv_id"], b["attachment_id"],
         time.time(), opened_by),
    )
    return get_bridge(db, bridge_id)


def mark_closed(db, bridge_id: str, closed_by: str, reason: str) -> bool:
    """Close once; False when it was already closed."""
    cur = db._exec(
        "UPDATE line_bridges SET closed_at=?, closed_by=?, close_reason=?"
        " WHERE id=? AND closed_at IS NULL",
        (time.time(), closed_by, reason, bridge_id),
    )
    return cur.rowcount == 1


def side_view(db, bridge: dict, key: str) -> dict:
    line = db.get_conversation(bridge[f"{key}_conv_id"]) or {}
    att = db.get_attachment(bridge[f"{key}_attachment_id"]) or {}
    return {"conv_id": bridge[f"{key}_conv_id"], "conv_name": line.get("name", ""),
            "attachment_id": bridge[f"{key}_attachment_id"], "name": att.get("name", "")}


def view(db, bridge: dict) -> dict:
    return {
        "id": bridge["id"], "opened_at": bridge["opened_at"], "opened_by": bridge["opened_by"],
        "closed_at": bridge["closed_at"], "closed_by": bridge["closed_by"],
        "close_reason": bridge["close_reason"],
        "sides": [side_view(db, bridge, "a"), side_view(db, bridge, "b")],
    }


def attachment_ref(db, att_id: str) -> dict | None:
    """The ``bridge`` field of an attachment payload, or None when not an ambassador."""
    bridge = open_bridge_for_attachment(db, att_id)
    if bridge is None:
        return None
    mine, theirs = side(bridge, att_id)
    peer = side_view(db, bridge, theirs)
    return {"bridge_id": bridge["id"], "peer_name": peer["name"],
            "peer_attachment_id": peer["attachment_id"], "peer_conv_id": peer["conv_id"],
            "peer_conv_name": peer["conv_name"]}


def audit_log(db, bridge_id: str) -> list[dict]:
    rows = db._exec(
        "SELECT m.*, c.name AS source_conv_name FROM messages m"
        " LEFT JOIN conversations c ON c.id = m.source_conv_id"
        " WHERE m.bridge_id=? ORDER BY m.id", (bridge_id,)).fetchall()
    return [dict(r) for r in rows]


def sent_in_window(db, bridge_id: str, att_id: str, now: float) -> int:
    """Copies this ambassador has delivered across the bridge in the current window."""
    return db._exec(
        "SELECT COUNT(*) AS n FROM messages WHERE bridge_id=? AND source_attachment_id=?"
        " AND audience_attachment_id IS NOT NULL AND created_at>?",
        (bridge_id, att_id, now - WINDOW_SECONDS),
    ).fetchone()["n"]
