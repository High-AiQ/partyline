"""Bounded window UIA snapshots; a fake provider and clock can be injected in tests."""
import heapq
import time
import uuid

from .uia_identity import element_id
from .uia_patterns import supported

MAX_ELEMENTS = 200
MAX_DEPTH = 20
MAX_TEXT = 160
BUDGET = 1.8  # seconds; uia_process kills a child that overruns it by KILL_SLACK
MAX_VISITS = 1000  # nodes read, including skipped wrappers, so empty panes cannot loop for ever
PAGE_SHARE = 150  # page elements beyond this wait behind the rest of the window
PAGE, BODY, CHROME, LATE = 0, 1, 2, 3  # traversal ranks: web page first, browser frame, toolbars, overflow
CHROME_TYPES = frozenset(("ToolBar", "MenuBar", "Menu", "Tab", "TitleBar"))
WRAPPERS = frozenset(("Pane", "Group", "Custom"))


def frame_bounds(rect, frame):
    if not frame:
        return None
    region, width, height = frame
    x, y, w, h = (region[k] for k in ("x", "y", "width", "height"))
    left, top = max(rect[0], x), max(rect[1], y)
    right, bottom = min(rect[2], x + w), min(rect[3], y + h)
    if left >= right or top >= bottom:
        return None
    return [round((left - x) * width / w), round((top - y) * height / h),
            round((right - x) * width / w), round((bottom - y) * height / h)]


def is_wrapper(props):
    """An unnamed, patternless container: it organises the tree but tells an agent nothing."""
    return (props.get("control_type") in WRAPPERS and not props.get("patterns")
            and not any(props.get(key) for key in ("name", "automation_id", "value")))


def child_kind(kind, control_type):
    if kind == PAGE or control_type == "Document":
        return PAGE
    return CHROME if kind == CHROME or control_type in CHROME_TYPES else BODY


def omission(reason, page_seen, heap, too_deep):
    """Say what a stopped walk left unread, so an agent asks for less rather than assume emptiness."""
    left = {"web page": 0, "browser chrome": 0, "other": 0}
    for _, _, _, _, _, kind in heap:
        left[("web page", "other", "browser chrome")[kind]] += 1
    parts = [reason, "page content partly read" if page_seen and left["web page"] else
             "page content read" if page_seen else "page content not reached"]
    parts += [f"{count} unread {name} subtrees" for name, count in left.items() if count]
    return "; ".join([*parts, f"{too_deep} nodes below the depth limit"] if too_deep else parts)


def snapshot(provider, frame=None, clock=time.monotonic, limit=MAX_ELEMENTS,
             depth_limit=MAX_DEPTH, budget=BUDGET):
    """Best-first walk: web-page subtrees before the browser frame, toolbars last; output in tree order."""
    deadline = clock() + budget
    found, visited, pages, seq = [], 0, 0, 0
    reason, page_seen, too_deep = "", False, 0
    heap = [(BODY, 0, 0, provider.root(), [], BODY)]
    while heap:
        if len(found) >= limit or visited >= MAX_VISITS:
            reason = "element limit"
            break
        if clock() >= deadline:
            reason = "time budget"
            break
        rank, depth, order, node, path, kind = heapq.heappop(heap)
        if rank == PAGE and pages >= PAGE_SHARE:
            heapq.heappush(heap, (LATE, depth, order, node, path, kind))
            continue
        visited += 1
        if not provider.same_window(node):
            continue
        props = provider.properties(node)
        control_type = props.get("control_type")
        page_seen = page_seen or control_type == "Document"
        if not (path and is_wrapper(props)):
            rect = provider.bounds(node)
            if provider.password(node):
                props.pop("value", None)
            for key in ("name", "automation_id", "value"):
                if key in props:
                    props[key] = str(props[key] or "")[:MAX_TEXT]
            props["id"] = element_id(provider, node, path)
            if actions := supported(props, not path):
                props["actions"] = actions
            props["bounds"] = list(rect)
            if pixels := frame_bounds(rect, frame):
                props["frame_bounds"] = pixels
            found.append((path, props))
            pages += kind == PAGE
        if depth >= depth_limit:
            too_deep += 1
            continue
        below = child_kind(kind, control_type)
        for index, child in enumerate(provider.children(node)):
            seq += 1
            heapq.heappush(heap, (below, depth + 1, seq, child, [*path, index], below))
    if not provider.current():
        return {"elements_unavailable": "window closed"}
    found.sort(key=lambda item: item[0])
    result = {"elements": [props for _, props in found], "truncated": bool(reason or too_deep),
              "paths": {props["id"]: path for path, props in found}, "snapshot_id": str(uuid.uuid4())}
    if result["truncated"]:
        result["truncation"] = omission(reason or "depth limit", page_seen, heap, too_deep)
    return result
