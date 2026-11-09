"""A captured window UIA tree kept on the server, so an agent reads it in small pieces."""
import json

MAX_NODES = 60_000  # nodes one capture call stores before it stops and offers `more`
MAX_TREE = 120_000  # nodes one stored tree keeps, however many `more` calls built it
OUT_BYTES = 4096  # UTF-8 bytes of one whole answer, as the MCP tool renders it
OUT_CHARS = 3400  # first estimate (UTF-8 bytes) of the room for lines; the whole answer is then measured
LEVEL_CAP = 6
TOGGLE = {0: "off", 1: "on", 2: "mixed"}
TEXT_FIELD = 160


def clean(value, limit=TEXT_FIELD):
    """One line without double quotes or control characters, so a line needs no JSON escaping."""
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in str(value or ""))
    return text.replace('"', "'")[:limit]


class Node:
    __slots__ = ("id", "parent", "type", "name", "value", "auto", "actions", "toggle", "flags",
                 "bounds", "frame")

    def __init__(self, item):
        self.id = str(item.get("id", ""))
        self.parent = item.get("parent")
        self.type = str(item.get("control_type") or "?")
        self.name = clean(item.get("name"))
        self.value = clean(item.get("value"))
        self.auto = clean(item.get("automation_id"), 40)
        self.actions = tuple(item.get("actions") or ())
        self.toggle = item.get("toggle")
        self.flags = tuple(flag for flag, on in (("off-screen", item.get("offscreen")),
                                                 ("disabled", item.get("enabled") is False),
                                                 ("focused", item.get("focused"))) if on)
        self.bounds = tuple(item["bounds"]) if item.get("bounds") else None
        self.frame = tuple(item["frame_bounds"]) if item.get("frame_bounds") else None

    def label(self, size=30):
        return f"{self.type} {self.name[:size]}".strip()


class Snapshot:
    """Nodes in tree order, with parent links; helper parts are appended as they arrive."""

    def __init__(self, snapshot_id, created):
        self.snapshot_id, self.created = snapshot_id, created
        self.nodes, self.order, self.kids = {}, [], {}
        self.cursor = None  # the helper's cursor for the unread rest of the window, if any
        self.note = ""
        self.old_helper = False  # ids from a helper that predates cursors: it reads one 200-element part
        self.changed = False  # a resumed read found the page different: elements may be missing or repeated
        self.counts = None

    def add(self, items):
        for item in items:
            node = Node(item)
            if not node.id or node.id in self.nodes or len(self.order) >= MAX_TREE:
                continue
            if self.order and not node.parent:
                node.parent = self.order[0]  # an older helper sends a flat list: hang it under the window
            self.nodes[node.id] = node
            self.order.append(node.id)
            self.kids.setdefault(node.parent if node.parent in self.nodes else None, []).append(node.id)
        self.counts = None

    @property
    def partial(self):
        return bool(self.cursor or self.note or self.changed)

    def descendants(self):
        """Descendant counts for every node: parents precede their children in tree order."""
        if self.counts is None:
            self.counts = dict.fromkeys(self.order, 0)
            for ident in reversed(self.order):
                parent = self.nodes[ident].parent
                if parent in self.counts:
                    self.counts[parent] += self.counts[ident] + 1
        return self.counts

    def children(self, ident):
        return [self.nodes[child] for child in self.kids.get(ident, ())]

    def subtree(self, ident):
        """Node ids at or below `ident`, in tree order; None when the id is not in this snapshot."""
        if ident is None:
            return self.order
        if ident not in self.nodes:
            return None
        wanted, found = {ident}, []
        for node_id in self.order[self.order.index(ident):]:
            if node_id in wanted:
                found.append(node_id)
                wanted.update(self.kids.get(node_id, ()))
        return found

    def path(self, ident, depth=3):
        names, node = [], self.nodes[ident]
        while node.parent in self.nodes and len(names) < depth:
            node = self.nodes[node.parent]
            names.append(node.label())
        return " > ".join(reversed(names))

    def line(self, node, level=0, bounds=False, extra=""):
        """`id Type "name" ="value" [actions] flags`, indented by nesting level."""
        parts = [" " * min(level, LEVEL_CAP) + node.id, node.type]
        if node.name:
            parts.append(f'"{node.name}"')
        elif node.auto:
            parts.append("#" + node.auto)
        if node.value:
            parts.append(f'="{node.value}"')
        if node.actions:
            parts.append("[" + ",".join(node.actions) + "]")
        if node.toggle in TOGGLE:
            parts.append("toggle:" + TOGGLE[node.toggle])
        parts.extend(node.flags)
        if bounds and node.bounds:
            parts.append("@" + ",".join(str(int(v)) for v in node.bounds))
            if node.frame:
                parts.append("frame@" + ",".join(str(int(v)) for v in node.frame))
        if extra:
            parts.append(extra)
        return " ".join(parts)


def fit(items, render, budget=OUT_CHARS):
    """Render items until the JSON-encoded output would pass the budget; return lines and how many fit."""
    lines, used = [], 0
    for item in items:
        line = render(item)
        cost = len(json.dumps(line, ensure_ascii=False).encode())
        if lines and used + cost > budget:
            break
        lines.append(line)
        used += cost
    return lines, len(lines)
