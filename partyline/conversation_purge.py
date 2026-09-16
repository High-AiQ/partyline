"""Purge logic for single lines and batch archived line purges."""

from __future__ import annotations

from .contracts import ConversationsChangedEvent
from .hierarchy import ancestors, child_ids
from .machine_scope import deny_purge_if_parent_refs
from .reports import purge_conversation as purge_reports
from .worktree_lifecycle import remove_for_line


async def execute_purge(runtime, media, db, conv: dict) -> None:
    conv_id = conv["id"]
    deny_purge_if_parent_refs(db, conv_id)
    await runtime.stop_attachments(conv_id)
    media.delete_conversation(conv_id)
    purge_reports(db, conv_id)
    remove_for_line(conv)
    db.delete_conversation(conv_id)
    runtime.sockets.pop(conv_id, None)


async def execute_purge_all_archived(runtime, media, db) -> dict:
    archived = db.list_conversations(archived=True)
    if not archived:
        return {"purged": [], "skipped": []}

    skipped: list[dict[str, str]] = []
    skipped_ids: set[str] = set()
    to_purge: dict[str, dict] = {}
    for conv in archived:
        parent_id = conv.get("parent_id")
        parent = db.get_conversation(parent_id) if parent_id else None
        if parent and not parent.get("archived_at"):
            skipped.append({"id": conv["id"], "reason": "parent is not archived"})
            skipped_ids.add(conv["id"])
        else:
            to_purge[conv["id"]] = conv

    changed = True
    while changed:
        changed = False
        for cid, conv in list(to_purge.items()):
            if conv.get("parent_id") in skipped_ids:
                del to_purge[cid]
                skipped.append({"id": cid, "reason": "parent is not archived"})
                skipped_ids.add(cid)
                changed = True

    changed = True
    while changed:
        changed = False
        for cid in list(to_purge):
            if any(child not in to_purge for child in child_ids(db, cid)):
                del to_purge[cid]
                skipped.append({"id": cid, "reason": "line has a child that is not archived"})
                changed = True

    targets = sorted(
        to_purge.values(), key=lambda c: len(ancestors(db, c["id"])), reverse=True
    )
    purged: list[str] = []
    for conv in targets:
        await execute_purge(runtime, media, db, conv)
        purged.append(conv["id"])

    if purged:
        await runtime.broadcast_all(ConversationsChangedEvent())
    return {"purged": purged, "skipped": skipped}
