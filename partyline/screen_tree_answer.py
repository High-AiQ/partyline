"""Pick the answer to a screen_elements call from the stored tree and the question asked."""
import json
from typing import Annotated

from fastapi import Query

from .screen_tree import OUT_BYTES
from .screen_tree_views import HINT, find, listing, summary, text


def elements_options(refresh: bool = False, more: bool = False,
                     root: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
                     depth: Annotated[int, Query(ge=1, le=3)] = 1,
                     query: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
                     control_type: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
                     text: bool = False, context: Annotated[int, Query(ge=0, le=5)] = 1,
                     offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0, bounds: bool = False):
    """What a screen_elements call asks of the stored snapshot; every query parameter is optional."""
    return dict(refresh=refresh, more=more, root=root, depth=depth, query=query,
                control_type=control_type, text=text, context=context, offset=offset, bounds=bounds)


def state(tree):
    result = {}
    if tree.partial:
        result["partial"] = tree.note or "the window is larger than one capture; call with more=true"
    if tree.old_helper:
        result["update_helper"] = ("this computer's Partyline helper is older and cannot read the whole "
                                   "page; update it")
    if tree.changed:
        result["changed"] = "the page changed while it was read, so some elements may be missing or " \
                            "repeated; take a new snapshot with refresh=true"
    return result


def size(result):
    """Bytes of the answer as the MCP tool renders it."""
    return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())


def assemble(tree, body, key, rows, dropped, resume=()):
    result = {**state(tree), **body}
    if key == "lines":
        if dropped:
            result["more"] = body.get("more", 0) + dropped
            result["next_offset"] = resume[len(rows)]
        result["lines"] = "\n".join(rows)
        if "more" in result:
            result["note"] = (f"{result['more']} more; pass offset={result['next_offset']} to continue, "
                              "or narrow the query/root")
    elif key:
        result[key] = rows
    return result


def answer(tree, grant, options):
    root, query, kind = options.get("root"), options.get("query"), options.get("control_type")
    if options.get("text"):
        body = text(tree, root, query, options.get("context", 1), options.get("offset", 0))
    elif query or kind:
        body = find(tree, query, kind, root, options.get("offset", 0), options.get("bounds", False))
    elif root:
        body = listing(tree, root, options.get("depth", 1), options.get("offset", 0))
    else:
        body = {"window_title": grant["title"][:100], "process_name": grant["process"][:60],
                **summary(tree), "hint": HINT}
    if body is None:
        return {"error": "unknown element id for this snapshot; take a new one with refresh=true"}
    key = next((name for name in ("lines", "outline") if name in body), None)
    rows = body.pop(key) if key else []
    resume = body.pop("resume", ())
    shown = len(rows)
    while True:  # drop trailing rows until the whole answer fits, and say how many are left
        result = assemble(tree, body, key, rows[:shown], len(rows) - shown, resume)
        if shown <= 1 or size(result) <= OUT_BYTES:
            break
        shown -= 1
    while rows and size(result) > OUT_BYTES and len(rows[0]) > 20:
        rows = [rows[0][:int(len(rows[0]) * 0.8)], *rows[1:]]  # one huge line: shorten it, never overflow
        result = assemble(tree, body, key, rows[:shown], len(rows) - shown, resume)
    return result
