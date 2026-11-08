"""Bounded window UIA snapshots; a fake provider and clock can be injected in tests."""
import time
import uuid

MAX_ELEMENTS = 200
MAX_DEPTH = 20
MAX_TEXT = 160
BUDGET = .3


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


def snapshot(provider, frame=None, clock=time.monotonic, limit=MAX_ELEMENTS,
             depth_limit=MAX_DEPTH, budget=BUDGET):
    deadline = clock() + budget
    result, truncated, visited = [], False, 0
    stack = [(provider.root(), 0)]
    while stack:
        if visited >= limit or clock() >= deadline:
            truncated = True
            break
        node, depth = stack.pop()
        visited += 1
        if not provider.same_window(node):
            continue
        rect = provider.bounds(node)
        props = provider.properties(node)
        if provider.password(node):
            props.pop("value", None)
        for key in ("name", "automation_id", "value"):
            if key in props:
                props[key] = str(props[key] or "")[:MAX_TEXT]
        props["id"] = len(result) + 1
        props["bounds"] = list(rect)
        if pixels := frame_bounds(rect, frame):
            props["frame_bounds"] = pixels
        result.append(props)
        if depth >= depth_limit:
            truncated = True
            continue
        children = provider.children(node)
        stack.extend((child, depth + 1) for child in reversed(children))
    if not provider.current():
        return {"elements_unavailable": "window closed"}
    return {"elements": result, "truncated": truncated, "snapshot_id": str(uuid.uuid4())}
