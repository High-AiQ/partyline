"""Bounded human-history reads; process delivery keeps its own cursor query."""


# Every read joins the line a message was said on, so a cross-line copy can
# be attributed ("via «Princess»") without a second query per message.
MESSAGE_SELECT = (
    "SELECT m.*, c.name AS source_conv_name FROM messages m"
    " LEFT JOIN conversations c ON c.id = m.source_conv_id"
)


def as_message(row) -> dict:
    """Every message dict carries source identity, even when the columns are null."""
    data = dict(row)
    for key in ("source_attachment_id", "source_conv_id", "source_conv_name",
                "audience_attachment_id"):
        data.setdefault(key, None)
    return data


def select_message_page(execute, conv_id, before_id=None, after_id=None, limit=20):
    if before_id is not None and after_id is not None:
        raise ValueError("choose before_id or after_id, not both")
    if after_id is not None:
        rows = execute(
            MESSAGE_SELECT + " WHERE m.conv_id=? AND m.id>? ORDER BY m.id LIMIT ?",
            (conv_id, after_id, limit + 1),
        ).fetchall()
        return [as_message(row) for row in rows[:limit]], len(rows) > limit

    where = "m.conv_id=?" if before_id is None else "m.conv_id=? AND m.id<?"
    args = (conv_id, limit + 1) if before_id is None else (conv_id, before_id, limit + 1)
    rows = execute(
        f"{MESSAGE_SELECT} WHERE {where} ORDER BY m.id DESC LIMIT ?", args
    ).fetchall()
    page = [as_message(row) for row in rows[:limit]]
    page.reverse()
    return page, len(rows) > limit
