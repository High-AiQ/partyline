"""Window UIA snapshots read in continuable parts; a fake provider and clock can be injected in tests."""
import time
import uuid

from .uia_identity import element_id
from .uia_patterns import supported
from .uia_walk_parts import Resolver, frame_bounds, is_wrapper

MAX_ELEMENTS = 2000  # elements per part; a part is a few hundred KB over the helper socket
MAX_TEXT = 160
BUDGET = 3.0  # seconds per part; uia_process kills a child that overruns it by KILL_SLACK
MAX_VISITS = 10000  # nodes read per part, including skipped wrappers, so empty panes cannot loop for ever
REASONS = {"limit": "element limit", "visits": "visit limit", "time": "time budget"}


def describe(provider, node, path, props, frame, parent):
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
    if parent:
        props["parent"] = parent
    return props


def next_unread(provider, resolver, stack, parents):
    """Per parent with unread children: its id, child count, and the next unread child (index and id)."""
    first = {}
    for path, _ in reversed(stack):  # the end of the stack is read first, so its lowest index per parent wins
        first.setdefault(path[:-1], path)
    saved = []
    for parent, path in first.items():
        if parent in parents:
            node = resolver.children(parent)[path[-1]]
            saved.append([list(parent), *parents[parent], path[-1], element_id(provider, node, list(path))])
    return saved


def snapshot(provider, frame=None, clock=time.monotonic, limit=MAX_ELEMENTS, budget=BUDGET,
             state=None, max_visits=MAX_VISITS):
    """Depth-first walk in tree order. A stopped walk returns `state`, the stack still to read."""
    resolver = Resolver(provider)  # fetches the root: that first read does not count against the budget
    deadline = clock() + budget
    stack = [(tuple(path), parent) for path, parent in state["stack"]] if state else [((), None)]
    changed = False
    parents = {}  # path -> (id, child count) of every node whose children wait on the stack
    if state:  # a part resumed after the page may have changed: drop what no longer sits where it did
        good = resolver.intact(state.get("parents", ()))
        parents = {tuple(path): (ident, count) for path, ident, count, _, _ in state.get("parents", ())}
        kept = [entry for entry in stack if entry[0][:-1] in good]
        changed, stack = len(kept) < len(stack), kept
    stack.reverse()  # the end of the list is the next node to read
    found, visited, reason = [], 0, ""
    while stack:
        if len(found) >= limit:
            reason = REASONS["limit"]
        elif visited >= max_visits:
            reason = REASONS["visits"]
        elif clock() >= deadline:
            reason = REASONS["time"]
        if reason:
            break
        path, parent = stack.pop()
        node = resolver.node(path)
        if node is None:
            continue  # the tree changed since the previous part
        visited += 1
        props = provider.properties(node)
        if not (path and is_wrapper(props)):
            props = describe(provider, node, list(path), props, frame, parent)
            parent = props["id"]
            found.append((path, props))
        kids = provider.children(node)
        resolver.kids[path] = kids
        own = parent if "id" in props else element_id(provider, node, list(path))  # a wrapper has no id yet
        parents[path] = (own, len(kids))
        for index in range(len(kids) - 1, -1, -1):
            stack.append(((*path, index), parent))
            resolver.nodes[(*path, index)] = kids[index]
    if not provider.current():
        return {"elements_unavailable": "window closed"}
    result = {"elements": [props for _, props in found], "truncated": bool(stack),
              "paths": {props["id"]: list(path) for path, props in found}, "snapshot_id": str(uuid.uuid4())}
    if stack:
        result["truncation"] = f"{reason}; {len(stack)} subtrees remain; continue with next_cursor"
        result["state"] = {"stack": [[list(path), parent] for path, parent in reversed(stack)],
                           "parents": next_unread(provider, resolver, stack, parents)}
    if changed:
        result["changed"] = True
    return result
