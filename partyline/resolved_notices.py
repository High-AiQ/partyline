"""Drop notices whose underlying state is already resolved before a resume replays them.

A restart hands a process its unread, addressed messages. Some of those are
alerts about a moment that has passed: a memory warning for a cap that was
since raised or a report wake for a report already acknowledged. Replaying
them reads as new work. The state is
checked here, at delivery time, never at queue time.
"""

from __future__ import annotations

import re

from .memory_sampler_state import warning_still_crosses

REPORT_WAKE_RE = re.compile(r"(?:@\S+ )?needs attention: report (\d+)")


def tag_memory_notice(db, message_id: int, attachment_id: str, cap: int) -> None:
    """Record which process and cap a queued memory warning was about."""
    db._exec(
        "INSERT OR REPLACE INTO memory_notice_refs(message_id, attachment_id, cap_bytes)"
        " VALUES(?,?,?)", (message_id, attachment_id, cap))


def _memory_live(runtime, message_id: int) -> bool:
    ref = runtime.db._exec(
        "SELECT attachment_id, cap_bytes FROM memory_notice_refs WHERE message_id=?",
        (message_id,)).fetchone()
    if ref is None:
        return True
    target = runtime.db.get_attachment(ref["attachment_id"])
    return target is not None and warning_still_crosses(runtime, target, ref["cap_bytes"])


def _report_ids(messages: list[dict]) -> dict[int, int]:
    """Message id -> report id, for report wakes."""
    found = {}
    for message in messages:
        match = REPORT_WAKE_RE.fullmatch(str(message.get("body") or "").strip())
        if match and message.get("sender_type") != "human":
            found[message["id"]] = int(match.group(1))
    return found


def drop_resolved(runtime, att: dict, messages: list[dict], *, keep=frozenset()) -> list[dict]:
    """Return ``messages`` without notices that no longer describe a live problem."""
    reports = _report_ids(messages)
    newest = {}
    for message_id, report in reports.items():
        newest[report] = max(newest.get(report, 0), message_id)
    kept = []
    for message in messages:
        mid = message["id"]
        if mid in keep:
            kept.append(message)
        elif mid in reports:
            row = runtime.db._exec(
                "SELECT acknowledged_at FROM line_reports WHERE id=?", (reports[mid],)).fetchone()
            if row is not None and row["acknowledged_at"] is None and newest[reports[mid]] == mid:
                kept.append(message)
        elif not _memory_live(runtime, mid):
            continue
        else:
            kept.append(message)
    return kept
