"""Listings shaped to fit one bounded MCP reply, in whole records.

`render` cuts a reply at 20,000 characters wherever that falls. A page of 50
messages was cut mid-record, losing the rest of the page and its `has_more`;
a long-lived root's `whoami` was mostly the names of retired lines.
"""

import json

from .render import MAX_TEXT

BUDGET = MAX_TEXT - 1000  # room for the envelope around the records


def compact(row):
    """A record without its unset fields: null, empty, or false."""
    if not isinstance(row, dict):
        return row
    return {key: value for key, value in row.items()
            if value is not None and value is not False and value != "" and value != []}


def message_page(page, forward: bool):
    """Keep as many whole messages as fit, nearest the reader's cursor, and say where to resume.

    ``forward`` is a page read with ``after_id``: its oldest messages are kept. Any other
    page keeps its newest.
    """
    if not isinstance(page, dict) or not isinstance(page.get("messages"), list):
        return page
    rows = [compact(row) for row in page["messages"]]
    kept, used = [], 0
    for row in rows if forward else reversed(rows):
        size = len(json.dumps(row, ensure_ascii=False, separators=(",", ":"))) + 1
        if kept and used + size > BUDGET:
            break
        kept.append(row)
        used += size
    if not forward:
        kept.reverse()
    result = {**page, "messages": kept}
    if len(kept) < len(rows):
        edge = kept[-1] if forward else kept[0]
        result.update(has_more=True, omitted=len(rows) - len(kept),
                      resume={"after_id" if forward else "before_id": edge.get("id")})
    return result


def live_children(children):
    """The lines a captain can still act on, and how many are retired."""
    rows = [row for row in children if isinstance(row, dict)] if isinstance(children, list) else []
    live = [{"id": row.get("id"), "name": row.get("name")} for row in rows
            if not row.get("archived_at")]
    return live, len(rows) - len(live)
