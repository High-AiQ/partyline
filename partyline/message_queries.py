"""Bounded human-history reads; process delivery keeps its own cursor query."""

from .message_visibility import (
    REACTION_NOTICE_LIKE, bridge_copy_sql, hide_reaction_notices_clause,
)


# Every read joins the line a message was said on, so a cross-line copy can
# be attributed ("via «Princess»") without a second query per message. A
# bridge row also names the line on the other side (``bridge_peer_conv_name``),
# read from the bridge itself so the tag survives the bridge closing.
MESSAGE_SELECT = (
    "SELECT m.*, c.name AS source_conv_name, pc.name AS bridge_peer_conv_name"
    " FROM messages m"
    " LEFT JOIN conversations c ON c.id = m.source_conv_id"
    " LEFT JOIN line_bridges lb ON lb.id = m.bridge_id"
    " LEFT JOIN conversations pc ON pc.id = CASE WHEN lb.a_conv_id = m.conv_id"
    " THEN lb.b_conv_id ELSE lb.a_conv_id END"
)


def as_message(row) -> dict:
    """Every message dict carries source identity, even when the columns are null."""
    data = dict(row)
    data.pop("task_private", None)  # a filter column, not part of the message
    for key in ("source_attachment_id", "source_conv_id", "source_conv_name",
                "audience_attachment_id", "bridge_id", "bridge_peer_conv_name"):
        data.setdefault(key, None)
    return data


def select_message_by_id(
    execute, conv_id: str, message_id: int, *, visible: bool = False
) -> dict | None:
    """One message; ``visible`` hides bridge copies from callers a person or process drives."""
    hidden = f" AND NOT {bridge_copy_sql()} AND m.task_private=0" if visible else ""
    row = execute(
        MESSAGE_SELECT + " WHERE m.conv_id=? AND m.id=?" + hidden, (conv_id, message_id)
    ).fetchone()
    return as_message(row) if row else None


def select_message_page(execute, conv_id, before_id=None, after_id=None, limit=20):
    if before_id is not None and after_id is not None:
        raise ValueError("choose before_id or after_id, not both")
    if after_id is not None:
        rows = execute(
            MESSAGE_SELECT + " WHERE m.conv_id=? AND m.id>? "
            + hide_reaction_notices_clause() + " ORDER BY m.id LIMIT ?",
            (conv_id, after_id, REACTION_NOTICE_LIKE, limit + 1),
        ).fetchall()
        return [as_message(row) for row in rows[:limit]], len(rows) > limit

    where = "m.conv_id=?" if before_id is None else "m.conv_id=? AND m.id<?"
    if before_id is None:
        args = (conv_id, REACTION_NOTICE_LIKE, limit + 1)
    else:
        args = (conv_id, before_id, REACTION_NOTICE_LIKE, limit + 1)
    rows = execute(
        f"{MESSAGE_SELECT} WHERE {where} "
        + hide_reaction_notices_clause()
        + " ORDER BY m.id DESC LIMIT ?",
        args,
    ).fetchall()
    page = [as_message(row) for row in rows[:limit]]
    page.reverse()
    return page, len(rows) > limit
