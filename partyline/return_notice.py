"""The text of a return-path notice, and whether a closing mention went nowhere."""

from __future__ import annotations

from .hierarchy import descendants
from .mention_relay import reaches_a_process
from .mentions import mentioned_names

EXCERPT = 280


def excerpt(body: str | None) -> str:
    """A one-line quote whose mentions cannot ring anyone.

    The notice is routed on purpose, so a quoted ``@name`` would wake that
    name on the requester's line — a second, accidental hand-off. The
    fullwidth sign reads the same and is not a mention.
    """
    if not body:
        return ""
    text = " ".join(body.split()).replace("@", "＠")
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1].rstrip() + "…"


def is_undeliverable_closing(db, finisher: dict, body: str) -> bool:
    """Whether a turn's closing words addressed only names that reach no process."""
    names = mentioned_names(body)
    names.discard(finisher["name"].lower())
    return bool(names and not reaches_a_process(db, finisher, names))


def format_notice(
    runtime, to: str, finisher: dict, on_line: str, said: str | None,
    since_id: int | None = None,
) -> str:
    """The private notice. The finisher is named without the sigil, so it cannot ring them."""
    where = pointer = ""
    if finisher["conv_id"] != on_line:
        line = runtime.db.get_conversation(finisher["conv_id"]) or {}
        where = f" on line «{line.get('name', '?')}»"
        # A child captain rung from above cannot read the parent line; a
        # pointer it will only get 403 from is worse than none.
        readable = finisher["conv_id"] in descendants(runtime.db, on_line)
        if since_id is not None and readable:
            pointer = (f". Read it all: GET /api/conversations/{finisher['conv_id']}"
                       f"/messages?after_id={since_id - 1}")
    tail = f"; last said: «{excerpt(said)}»" if said else " and said nothing"
    return (
        f"↩ @{to} — {finisher['name']}{where} ended its turn without handing off "
        f"to any process{tail}{pointer}"
    )
