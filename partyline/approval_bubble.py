"""Human-gated requests bubble to the root line, where the person looks.

A write-set, memory or restart request filed on a child line used to post
only on that line, and the person — who talks to the root captain and never
reads sublines — found it by luck. `bubble_approval` runs at each filing
path when the line has ancestors: one notice on the root names the line,
the requester and the approve call, and @mentions the root's captain so
that process actually wakes and can explain the request in context. A
request filed on the root itself is already where the person looks, so
nothing bubbles. `pending_approvals` is the same picture as a count: what
is still waiting anywhere in a line's subtree, for the staffing line.
"""

from __future__ import annotations

from .hierarchy import ancestors, lead_attachment, subtree_conversation_ids
from .system_notice import post_system_notice

DETAIL_LIMIT = 160


def _clip(text: str, limit: int = DETAIL_LIMIT) -> str:
    """One line, at most ``limit`` characters: a pointer, not the whole file."""
    cleaned = " ".join(str(text).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


async def bubble_approval(runtime, conv_id: str, *, kind: str, requester: str,
                          detail: str, approve: str, actor=None) -> None:
    """Post the pending-approval notice on the tree's root and ring its captain.

    The forced mention route is what wakes: system notices are otherwise
    never delivered. The routed body names the requester too, but relays skip
    system notices, so only a process on the root — the captain — is rung,
    and the captain that filed the request itself is never rung about its own
    filing (the same-speaker rule).
    """
    db = runtime.db
    chain = ancestors(db, conv_id)
    if not chain:
        return
    root_id = chain[-1]
    root = db.get_conversation(root_id)
    if root is None or root.get("archived_at"):
        return
    line = db.get_conversation(conv_id)
    captain = lead_attachment(db, root_id)
    ring = f" @{captain['name']}" if captain else ""
    body = (f"⚑ approval pending on «{line['name'] if line else conv_id}»: {kind} "
            f"from @{requester} — {_clip(detail)} (approve: {approve}){ring}")
    msg = await post_system_notice(runtime, root_id, body, actor=actor)
    if captain:
        await runtime.route_mentions(root_id, msg, force=True)


def pending_approvals(db, conv_id: str, *, runtime=None) -> list[tuple[str, str]]:
    """(line name, kind) for every approval still pending in conv_id's subtree.

    Oldest first. Write-set and memory requests are rows; the restart request
    is a host-wide runtime singleton, counted when the caller can see one and
    its line lies in the subtree. A decided request's row is gone, so the
    count falls as approvals and denials land. A minimal db without these
    queries counts nothing, as ``handoff_rider`` does.
    """
    try:
        rows: list[tuple[float, str, str]] = []
        for row in db._exec(
                "SELECT conv_id, created_at FROM conversation_write_grant_requests").fetchall():
            rows.append((row["created_at"], row["conv_id"], "write-set"))
        for row in db._exec(
                "SELECT conv_id, created_at FROM memory_limit_requests").fetchall():
            rows.append((row["created_at"], row["conv_id"], "memory"))
        request = getattr(runtime, "restart_request", None) if runtime is not None else None
        if request is not None:
            rows.append((request.created_at, request.conversation_id, "restart"))
        subtree = set(subtree_conversation_ids(db, conv_id))
        found: list[tuple[str, str]] = []
        for _created, line_id, kind in sorted(rows):
            if line_id not in subtree:
                continue
            conv = db.get_conversation(line_id)
            found.append((conv["name"] if conv else line_id, kind))
        return found
    except AttributeError:
        return []
