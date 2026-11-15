"""Bounded look marks and their text, derived from the exact same captured nodes."""
from .screen_tree import Node, clean
from .screen_tree_query import matcher

MAX_BOXES = 80


def candidates(elements, query=None):
    matches = matcher(query)
    found = []
    for item in elements:
        node = Node(item)
        box, kind = node.bounds, "screen"
        if not box:
            box, kind = node.cached.get("viewport_bounds"), "viewport"
        if ("off" in node.flags or "hidden" in node.flags or not box or len(box) != 4
                or box[2] <= box[0] or box[3] <= box[1]
                or (matches and not matches(node.name))):
            continue
        area = (box[2] - box[0]) * (box[3] - box[1])
        found.append((not bool(node.actions), area, node, kind, box))
    found.sort(key=lambda row: row[:2])
    return found


def inputs(found, start):
    return [{"n": start + i, "id": node.id, "role": node.type, "name": node.name[:40], kind: list(box)}
            for i, (_, _, node, kind, box) in enumerate(found)]


def line(number, node):
    actions = ",".join(node.actions) or "no actions"
    state = list(node.flags)
    if node.toggle is not None:
        state.append("checked=" + str({0: "false", 1: "true", 2: "mixed"}.get(node.toggle, node.toggle)))
    if node.cached.get("selected") is not None:
        state.append("selected=" + str(node.cached["selected"]).lower())
    if node.value:
        state.append('value="' + clean(node.value, 80) + '"')
    return f'[{number}] {node.type} "{clean(node.name, 80)}" {actions}' + (
        " " + " ".join(state) if state else "")
