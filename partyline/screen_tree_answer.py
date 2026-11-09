"""Pick the answer to a screen_elements call from the stored tree and the question asked."""
import json
from typing import Annotated

from fastapi import Query

from .screen_tree import OUT_BYTES
from .screen_tree_views import HINT, changes, detail, find, listing, summary, text


def elements_options(refresh: bool = False, more: bool = False,
                     root: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
                     depth: Annotated[int, Query(ge=1, le=3)] = 1,
                     query: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
                     value: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
                     id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
                     control_type: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
                     text: bool = False, changes: bool = False,
                     context: Annotated[int, Query(ge=0, le=5)] = 1,
                     offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0, bounds: bool = False):
    """What a screen_elements call asks of the stored snapshot; every query parameter is optional."""
    return dict(refresh=refresh, more=more, root=root, depth=depth, query=query, value=value, id=id,
                control_type=control_type, text=text, changes=changes, context=context, offset=offset,
                bounds=bounds)


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


def pick(tree, grant, options):
    root, query, kind, value = (options.get(key) for key in ("root", "query", "control_type", "value"))
    if options.get("id"):
        return detail(tree, options["id"], options.get("bounds", False))
    if options.get("changes") and not (options.get("text") or query or kind or value or root):
        return changes(tree, options.get("offset", 0))
    if options.get("text"):
        return text(tree, root, query, options.get("context", 1), options.get("offset", 0))
    if query or kind or value:
        return find(tree, query, kind, root, options.get("offset", 0), options.get("bounds", False), value)
    if root:
        return listing(tree, root, options.get("depth", 1), options.get("offset", 0))
    return {"window_title": grant["title"][:100], "process_name": grant["process"][:60],
            **summary(tree), "hint": HINT}


def answer(tree, grant, options, budget=OUT_BYTES):
    body = pick(tree, grant, options)
    if body is None:
        return {"error": "unknown element id: not in this snapshot (gone, or not read yet: more=true, "
                         "or find it again)"}
    if options.get("changes") and "diff" not in body:
        body["diff"] = changes(tree)["diff"]
    key = next((name for name in ("lines", "outline") if name in body), None)
    rows = body.pop(key) if key else []
    resume = body.pop("resume", ())
    shown = len(rows)
    while True:  # drop trailing rows until the whole answer fits, and say how many are left
        result = assemble(tree, body, key, rows[:shown], len(rows) - shown, resume)
        if shown <= 1 or size(result) <= budget:
            break
        shown -= 1
    while rows and size(result) > budget and len(rows[0]) > 20:
        rows = [rows[0][:int(len(rows[0]) * 0.8)], *rows[1:]]  # one huge line: shorten it, never overflow
        result = assemble(tree, body, key, rows[:shown], len(rows) - shown, resume)
    return result
