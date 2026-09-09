"""Conversation parent pointers: descendants, cycles, and child listing."""

from __future__ import annotations

import time

from .db import Db


class HierarchyError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def parent_id_of(conv: dict | None) -> str | None:
    if not conv:
        return None
    value = conv.get("parent_id")
    return value or None


def child_ids(db: Db, conv_id: str) -> list[str]:
    rows = db._exec(
        "SELECT id FROM conversations WHERE parent_id=? ORDER BY created_at",
        (conv_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def descendants(db: Db, conv_id: str) -> list[str]:
    found: list[str] = []
    queue = list(child_ids(db, conv_id))
    seen = set(queue)
    while queue:
        current = queue.pop(0)
        found.append(current)
        for child in child_ids(db, current):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return found


def ancestors(db: Db, conv_id: str) -> list[str]:
    found: list[str] = []
    current = parent_id_of(db.get_conversation(conv_id))
    while current:
        if current in found:
            break
        found.append(current)
        current = parent_id_of(db.get_conversation(current))
    return found


def is_descendant(db: Db, ancestor: str, conv_id: str) -> bool:
    return conv_id in descendants(db, ancestor)


def would_cycle(db: Db, conv_id: str, parent_id: str) -> bool:
    if conv_id == parent_id:
        return True
    return conv_id in ancestors(db, parent_id) or is_descendant(db, conv_id, parent_id)


def create_child_conversation(db: Db, parent_id: str, child_id: str, name: str) -> dict:
    parent = db.get_conversation(parent_id)
    if parent is None:
        raise HierarchyError(404, "parent line not found")
    if parent.get("archived_at"):
        raise HierarchyError(409, "restore the parent before creating a child")
    if would_cycle(db, child_id, parent_id):
        raise HierarchyError(400, "that parent would cycle the line tree")
    db._exec(
        "INSERT INTO conversations(id,name,created_at,parent_id) VALUES(?,?,?,?)",
        (child_id, name, time.time(), parent_id),
    )
    return db.get_conversation(child_id)


def set_parent(db: Db, conv_id: str, parent_id: str | None) -> dict:
    # Serialize the graph check with the update across threads and connections.
    with db._runtime_serialized():
        return _set_parent(db, conv_id, parent_id)


def _set_parent(db: Db, conv_id: str, parent_id: str | None) -> dict:
    conv = db.get_conversation(conv_id)
    if conv is None:
        raise HierarchyError(404, "line not found")
    if parent_id:
        parent = db.get_conversation(parent_id)
        if parent is None:
            raise HierarchyError(404, "parent line not found")
        if conv.get("archived_at") or parent.get("archived_at"):
            raise HierarchyError(409, "restore both lines before linking them")
        if would_cycle(db, conv_id, parent_id):
            raise HierarchyError(400, "that parent would cycle the line tree")
    db._exec("UPDATE conversations SET parent_id=? WHERE id=?", (parent_id, conv_id))
    return db.get_conversation(conv_id)


def set_lead(db: Db, conv_id: str, attachment_id: str | None) -> None:
    if attachment_id is None:
        db._exec("UPDATE attachments SET is_lead=0 WHERE conv_id=?", (conv_id,))
        return
    att = db.get_attachment(attachment_id)
    if att is None or att["conv_id"] != conv_id:
        raise HierarchyError(404, "attachment is not on this line")
    with db.lock:
        db.conn.execute(
            "UPDATE attachments SET is_lead=0 WHERE conv_id=?", (conv_id,)
        )
        db.conn.execute(
            "UPDATE attachments SET is_lead=1 WHERE id=?", (attachment_id,)
        )
        db.conn.commit()


def stamp_source(db: Db, message_id: int, principal) -> dict:
    if getattr(principal, "kind", None) != "machine":
        return {}
    db._exec(
        "UPDATE messages SET source_attachment_id=?, source_conv_id=? WHERE id=?",
        (principal.attachment_id, principal.conv_id, message_id),
    )
    return {
        "source_attachment_id": principal.attachment_id,
        "source_conv_id": principal.conv_id,
    }


def lead_attachment(db: Db, conv_id: str) -> dict | None:
    row = db._exec(
        "SELECT * FROM attachments WHERE conv_id=? AND is_lead=1",
        (conv_id,),
    ).fetchone()
    if row is None:
        return None
    return db.get_attachment(row["id"])
