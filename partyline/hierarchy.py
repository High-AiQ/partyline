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


def tree_conversation_ids(db: Db, conv_id: str) -> list[str]:
    """Every line of conv_id's tree, reached from the root.

    Walking to the root first means every caller — a child, the root itself,
    a mid-branch line — sees the same set, which is what tree-wide rules need.
    """
    lineage = ancestors(db, conv_id)
    root = lineage[-1] if lineage else conv_id
    return [root, *descendants(db, root)]


def subtree_conversation_ids(db: Db, conv_id: str) -> list[str]:
    """conv_id and every line hanging under it — no ancestors."""
    return [conv_id, *descendants(db, conv_id)]


def tree_live_name_conflict(db: Db, conv_id: str, name: str) -> dict | None:
    """A live attachment anywhere in conv_id's tree bearing this handle.

    One tree is one mention namespace: `@name` must resolve to exactly one
    live process, so two live rows sharing a handle — even case-insensitively
    distinct — would let a mention ring a stranger on a related line. Every
    door that can create a live row checks here first.
    """
    wanted = name.lower()
    for line_id in tree_conversation_ids(db, conv_id):
        for att in db.list_attachments(line_id):
            if att["status"] in ("starting", "running") and att["name"].lower() == wanted:
                return att
    return None


def tree_merge_name_conflicts(db: Db, conv_id: str, parent_id: str) -> list[str]:
    """Handles that two distinct live attachments would share after linking.

    The surviving namespace is the parent's whole root tree plus the moving
    line's subtree, counting each attachment once. The root walk on the
    parent side is the point: linking under a non-root parent must see that
    parent's ancestors, whose rows join the tree too. Counting by attachment
    id keeps the two legal cases clean — re-linking to the present parent
    overlaps the sets completely and is a no-op, and moving out of an old
    tree leaves the old tree's rows behind. A real collision is one handle
    live on two different rows of the union.
    """
    by_name: dict[str, dict[str, str]] = {}
    for line_id in {
        *tree_conversation_ids(db, parent_id),
        *subtree_conversation_ids(db, conv_id),
    }:
        for att in db.list_attachments(line_id):
            if att["status"] in ("starting", "running"):
                by_name.setdefault(att["name"].lower(), {})[att["id"]] = att["name"]
    return sorted(next(iter(sides.values())) for sides in by_name.values() if len(sides) > 1)


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
    current = parent_id_of(conv)
    if parent_id:
        if current and current != parent_id:
            # A line's parent is set once or cleared, never re-pointed: moves
            # reshuffle whole trees for no user story. Unlink first, then link.
            raise HierarchyError(
                409, "unlink this line before linking it to a different parent"
            )
        if current == parent_id:
            return conv  # re-saving the present parent changes nothing
        parent = db.get_conversation(parent_id)
        if parent is None:
            raise HierarchyError(404, "parent line not found")
        if conv.get("archived_at") or parent.get("archived_at"):
            raise HierarchyError(409, "restore both lines before linking them")
        if would_cycle(db, conv_id, parent_id):
            raise HierarchyError(400, "that parent would cycle the line tree")
        # Set-once link only: the merge guard never sees a re-save.
        conflicts = tree_merge_name_conflicts(db, conv_id, parent_id)
        if conflicts:
            quoted = " and ".join(f"'{name}'" for name in conflicts)
            raise HierarchyError(
                409, f"linking would put two live processes named {quoted} in one tree"
            )
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
