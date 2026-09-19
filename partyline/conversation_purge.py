"""Purge logic for single lines and batch archived line purges."""

from __future__ import annotations

from .contracts import ConversationsChangedEvent
from .hierarchy import ancestors, child_ids
from .machine_scope import deny_purge_if_parent_refs
from .reports import purge_conversation as purge_reports
from .review_worktrees import prune_review_worktrees
from .worktree_lifecycle import remove_for_line


async def execute_purge(runtime, media, db, conv: dict) -> None:
    conv_id = conv["id"]
    deny_purge_if_parent_refs(db, conv_id)
    await runtime.stop_attachments(conv_id)
    media.delete_conversation(conv_id)
    purge_reports(db, conv_id)
    remove_for_line(conv)
    prune_review_worktrees(db, conv_id)
    db.delete_conversation(conv_id)
    runtime.sockets.pop(conv_id, None)


async def execute_purge_all_archived(runtime, media, db) -> dict:
    archived = db.list_conversations(archived=True)
    if not archived:
        return {"purged": [], "skipped": []}

    skipped: list[dict[str, str]] = []
    to_purge: dict[str, dict] = {}
    for conv in archived:
        to_purge[conv["id"]] = conv

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
