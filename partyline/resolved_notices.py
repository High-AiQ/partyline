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

REPORT_WAKE_RE = re.compile(
    r"(?:@\S+ )?needs attention: report (\d+)(?: from line \S+|; fetch with .*)?")
APPROVAL_APPROVE_RE = (
    ("write-set", re.compile(
        r"⚑ (?:approval pending|write-set decision needed).*"
        r"\((?:approve|request): POST /api/conversations/([^/\s]+)/write-set/request/([^/\s]+)/approve")),
    ("memory", re.compile(
        r"⚑ approval pending.*\((?:approve|request): POST /api/memory-requests/([^/\s]+)/approve")),
    ("restart", re.compile(
        r"⚑ approval pending.*\((?:approve|request): POST /api/restart-request/([^/\s]+)/approve")),
)


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


def _approval_ids(messages: list[dict]) -> dict[int, tuple]:
    """Message id -> (kind, line id, request id), for approval bubbles."""
    found = {}
    for message in messages:
        if message.get("sender_type") == "human":
            continue
        body = str(message.get("body") or "")
        for kind, pattern in APPROVAL_APPROVE_RE:
            match = pattern.search(body.strip())
            if match:
                parts = match.groups()
                found[message["id"]] = ((kind, *parts) if kind == "write-set"
                                        else (kind, "", *parts))
                break
    return found


def _approval_live(runtime, ref: tuple) -> bool:
    kind, conv_id, request_id = ref
    if kind == "write-set":
        return runtime.db._exec(
            "SELECT 1 FROM conversation_write_grant_requests WHERE conv_id=? AND id=?",
            (conv_id, request_id)).fetchone() is not None
    if kind == "memory":
        return runtime.db._exec(
            "SELECT 1 FROM memory_limit_requests WHERE id=? AND expired_at IS NULL",
            (request_id,)).fetchone() is not None
    request = getattr(runtime, "restart_request", None)
    return request is not None and request.id == request_id


def drop_resolved(runtime, att: dict, messages: list[dict], *, keep=frozenset()) -> list[dict]:
    """Return ``messages`` without notices that no longer describe a live problem."""
    reports = _report_ids(messages)
    approvals = _approval_ids(messages)
    newest = {}
    for message_id, ref in (*reports.items(), *approvals.items()):
        newest[ref] = max(newest.get(ref, 0), message_id)
    kept = []
    for message in messages:
        mid = message["id"]
        if mid in approvals:
            # A decided request must not replay even from an explicitly held batch.
            if _approval_live(runtime, approvals[mid]) and newest[approvals[mid]] == mid:
                kept.append(message)
        elif mid in keep:
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


def drop_acknowledged_reports(db, messages: list[dict], *, keep=frozenset()) -> list[dict]:
    """``messages`` without wakes for reports a person or captain has already acknowledged."""
    wakes = _report_ids(messages)
    if not wakes:
        return messages
    done = {report for report in set(wakes.values())
            if (row := db._exec("SELECT acknowledged_at FROM line_reports WHERE id=?",
                                (report,)).fetchone()) is not None and row["acknowledged_at"] is not None}
    return [m for m in messages if m["id"] in keep or wakes.get(m["id"]) not in done]
