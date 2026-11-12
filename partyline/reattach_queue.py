"""What the restart plan is still bringing back, said where people look for it.

A restart plan resumes processes one at a time, so for a while the processes
queued behind the current one are neither live nor gone. Every message that
would otherwise read as "gone" asks this module first.
"""

from __future__ import annotations

FINISHED = "sequential reattachment finished"


def queued_ids(runtime) -> set[str]:
    """Attachments of an in-progress restart plan that are not live yet."""
    planned = getattr(runtime, "restart_plan_order", None)
    if not planned:
        return set()
    return (set(runtime.reattaching) & set(planned)) - set(runtime.live)


def is_queued(runtime, att_id: str | None) -> bool:
    return bool(att_id) and att_id in queued_ids(runtime)


def queued_attachments(runtime, line_ids=None) -> list[dict]:
    """Queued attachment rows in plan order, optionally limited to some lines."""
    queued = queued_ids(runtime)
    rows = []
    for att_id in getattr(runtime, "restart_plan_order", ()):
        if att_id not in queued:
            continue
        att = runtime.db.get_attachment(att_id)
        if att is not None and (line_ids is None or att["conv_id"] in line_ids):
            rows.append(att)
    return rows


def queue_label(runtime, rows: list[dict], *, line: str | None = None, at: str = "@") -> str:
    """``@a, @b «line»`` — a line is named only where it differs from ``line``."""
    names = []
    for att in rows:
        conv = runtime.db.get_conversation(att["conv_id"]) or {}
        suffix = "" if att["conv_id"] == line else f" «{conv.get('name', '?')}»"
        names.append(f"{at}{att['name']}{suffix}")
    return ", ".join(names)


def queue_notice(runtime, rows: list[dict], *, line: str) -> str:
    """The paragraph a restart's requester and each affected line's captain read."""
    count = len(rows)
    noun = "process is" if count == 1 else "processes are"
    return (
        f"{count} previously attached {noun} queued to come back on their own, one at a "
        f"time: {queue_label(runtime, rows, line=line)}. Do not restart, reattach or "
        "re-create them by hand (captain(op=\"restart_implementer\" or \"restart_reviewer\") would fight the "
        f"plan); wait for the \"{FINISHED}\" notice that follows."
    ) if rows else ""


def queued_detail(role: str) -> str:
    return (
        f"this task's {role} is queued for automatic reattachment after the restart; wait "
        f"for the \"{FINISHED}\" notice instead of calling restart_{role}"
    )


def no_live_detail(runtime, att: dict | None, role: str, purpose: str = "") -> str:
    """The 409 text for a task worker that is not running: queued, or truly detached."""
    if att is not None and is_queued(runtime, att["id"]):
        return queued_detail(role)
    return f"this task has no live {role}{purpose}; call restart_{role}"


async def post_start_notices(runtime, covered, conv_id: str, text: str) -> tuple[dict, set]:
    """Post the start banner on each covered line; return its ids and the lines told of a queue.

    The requester's line hears about every queued process; any other line, about its own.
    """
    notice_ids, queued_lines = {}, set()
    for line in covered:
        queue = queue_notice(
            runtime, queued_attachments(runtime, None if line == conv_id else {line}), line=line)
        notice = await runtime.post_message(
            line, "system", "system", text + (f"\n\n{queue}" if queue else ""))
        notice_ids[line] = notice["id"]
        if queue:
            queued_lines.add(line)
    return notice_ids, queued_lines


async def post_finish_notices(runtime, covered, queued_lines: set, text: str) -> None:
    """Close the run on each line, and wake the live captains who were told to wait for it."""
    from .mention_relay import post_private
    for line in covered:
        await runtime.post_message(line, "system", "system", text)
        for att in runtime.db.list_attachments(line):
            if line in queued_lines and att.get("is_lead") and att["id"] in runtime.live:
                await post_private(runtime, line, "system", "system", text,
                                   audience=att["id"], private=True)
