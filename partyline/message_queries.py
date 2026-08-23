"""Bounded human-history reads; process delivery keeps its own cursor query."""


def select_message_page(execute, conv_id, before_id=None, after_id=None, limit=20):
    if before_id is not None and after_id is not None:
        raise ValueError("choose before_id or after_id, not both")
    if after_id is not None:
        rows = execute(
            "SELECT * FROM messages WHERE conv_id=? AND id>? ORDER BY id LIMIT ?",
            (conv_id, after_id, limit + 1),
        ).fetchall()
        return [dict(row) for row in rows[:limit]], len(rows) > limit

    where = "conv_id=?" if before_id is None else "conv_id=? AND id<?"
    args = (conv_id, limit + 1) if before_id is None else (conv_id, before_id, limit + 1)
    rows = execute(
        f"SELECT * FROM messages WHERE {where} ORDER BY id DESC LIMIT ?", args
    ).fetchall()
    page = [dict(row) for row in rows[:limit]]
    page.reverse()
    return page, len(rows) > limit
