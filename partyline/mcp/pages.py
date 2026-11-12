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


def _size(row) -> int:
    return len(json.dumps(row, ensure_ascii=False, separators=(",", ":"))) + 1


def message_page(page, forward: bool, around=None):
    """Keep as many whole messages as fit, nearest the reader's cursor, and say where to resume.

    ``forward`` is a page read with ``after_id``: its oldest messages are kept. A page read
    ``around`` a message keeps that message and grows outwards from it, a neighbour on each
    side in turn. Any other page keeps its newest.
    """
    if not isinstance(page, dict) or not isinstance(page.get("messages"), list):
        return page
    rows = [compact(row) for row in page["messages"]]
    centre = next((index for index, row in enumerate(rows)
                   if isinstance(row, dict) and row.get("id") == around), None)
    if around is not None and centre is not None:
        low, high = _around(rows, centre)
    else:
        order = rows if forward else list(reversed(rows))
        count, used = 0, 0
        for row in order:
            if count and used + _size(row) > BUDGET:
                break
            count, used = count + 1, used + _size(row)
        low, high = (0, count) if forward else (len(rows) - count, len(rows))
    kept = rows[low:high]
    result = {**page, "messages": kept}
    if len(kept) < len(rows):
        resume = {}
        if low > 0 and not forward:
            resume["before_id"] = kept[0].get("id")
        if high < len(rows) and (forward or around is not None):
            resume["after_id"] = kept[-1].get("id")
        result.update(omitted=len(rows) - len(kept), resume=resume)
        if around is None:
            result["has_more"] = True
        else:
            result.update(has_more_before=bool(page.get("has_more_before")) or low > 0,
                          has_more_after=bool(page.get("has_more_after")) or high < len(rows))
    return result


def _around(rows, centre):
    """The widest run of whole messages around ``rows[centre]`` that fits."""
    low, high, used = centre, centre + 1, _size(rows[centre])
    older = newer = True
    while older or newer:
        older = older and low > 0 and used + _size(rows[low - 1]) <= BUDGET
        if older:
            low, used = low - 1, used + _size(rows[low - 1])
        newer = newer and high < len(rows) and used + _size(rows[high]) <= BUDGET
        if newer:
            high, used = high + 1, used + _size(rows[high])
    return low, high


def live_children(children):
    """The lines a captain can still act on, and how many are retired."""
    rows = [row for row in children if isinstance(row, dict)] if isinstance(children, list) else []
    live = [{"id": row.get("id"), "name": row.get("name")} for row in rows
            if not row.get("archived_at")]
    return live, len(rows) - len(live)
