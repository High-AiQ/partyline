"""A task process and its root captain cannot acknowledge each other forever.

`ack_limits` never limits a captain and reads one line's history, so the pair
that talks across lines — a task's process and the root captain — relayed every
bare "ack" to the other, each relay waking the peer for another. The third bare
message in a row between the pair is stored but not relayed, and its speaker
is told the rule. A question, a SHA, a file, a long reply, or an accept or
report since the streak began ends it.
"""

from .ack_limits import SCAN, _has_files, _real_work

RULE = ("acknowledgment not relayed; reply only with results, questions or a status change "
        "— react \U0001f440 instead")


def is_bare(db, message: dict) -> bool:
    body = message.get("body") or ""
    return ("?" not in body and not _real_work(body)
            and not (message.get("id") and _has_files(db, message["id"])))


def pair_lines(db, from_conv: str, to_conv: str) -> tuple[str, str] | None:
    """``(task line, root line)`` when the two lines are a task and its root."""
    for task_line, root_line in ((from_conv, to_conv), (to_conv, from_conv)):
        row = db._exec("SELECT 1 FROM task_reviews WHERE conv_id=? AND root_id=?",
                       (task_line, root_line)).fetchone()
        if row:
            return task_line, root_line
    return None


def withheld_ack(db, from_conv: str, to_conv: str, message: dict) -> bool:
    """Whether this message is the third bare one between a task and its root captain."""
    lines = pair_lines(db, from_conv, to_conv)
    if lines is None or not is_bare(db, message):
        return False
    rows = db._exec(
        "SELECT id, sender_type, body, created_at FROM messages WHERE conv_id IN (?,?)"
        " AND id != ? AND id < ? AND sender_type != 'system' AND audience_attachment_id IS NULL"
        " ORDER BY id DESC LIMIT ?", (*lines, message["id"], message["id"], SCAN)).fetchall()
    streak, oldest = 0, None
    for row in rows:
        if row["sender_type"] != "agent" or not is_bare(db, dict(row)):
            break
        streak, oldest = streak + 1, row["created_at"]
    if streak < 2:
        return False
    recent = db._exec(
        "SELECT 1 FROM accept_history WHERE conv_id=? AND created_at>=? UNION ALL "
        "SELECT 1 FROM line_reports WHERE parent_conv_id=? AND created_at>=? LIMIT 1",
        (lines[0], oldest, lines[1], oldest)).fetchone()
    return recent is None
