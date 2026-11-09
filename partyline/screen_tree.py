"""A captured window UIA tree kept on the server, so an agent reads it in small pieces."""
import json

from .screen_tree_ids import IdSpace, fingerprint, identity, named

MAX_NODES = 60_000  # nodes one capture call stores before it stops and offers `more`
MAX_TREE = 120_000  # nodes one stored tree keeps, however many `more` calls built it
OUT_BYTES = 4096  # UTF-8 bytes of one whole answer, as the MCP tool renders it
OUT_CHARS = 3400  # first estimate (UTF-8 bytes) of the room for lines; the whole answer is then measured
LEVEL_CAP = 6
WRAPPERS = {"Group", "Pane", "Custom"}
TOGGLE = {0: "off", 1: "on", 2: "mixed"}
NAME_FIELD = 1000  # characters of a name kept; lines clip it, `id` reads it whole
VALUE_FIELD = 600
LINE_NAME = 240  # characters of a name shown on a line
LINE_VALUE = 80


def clean(value, limit=NAME_FIELD):
    """One line without double quotes or control characters, so a line needs no JSON escaping."""
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in str(value or ""))
    return text.replace('"', "'")[:limit]


def clip(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Node:
    __slots__ = ("id", "helper", "parent", "type", "name", "value", "auto", "actions", "toggle", "flags",
                 "bounds", "frame")

    def __init__(self, item):
        self.id = self.helper = str(item.get("id", ""))  # id is replaced by the stable one on add
        self.parent = item.get("parent")
        self.type = clean(item.get("control_type") or "?", 40)
        self.name = clean(item.get("name"))
        self.value = clean(item.get("value"), VALUE_FIELD)
        self.auto = clean(item.get("automation_id"), 40)
        self.actions = tuple(item.get("actions") or ())
        self.toggle = item.get("toggle")
        self.flags = tuple(flag for flag, on in (("off", item.get("offscreen")),
                                                 ("disabled", item.get("enabled") is False),
                                                 ("focused", item.get("focused"))) if on)
        self.bounds = tuple(item["bounds"]) if item.get("bounds") else None
        self.frame = tuple(item["frame_bounds"]) if item.get("frame_bounds") else None

    def label(self, size=24):
        return f"{self.type} {self.name[:size]}".strip()


class Snapshot:
    """Nodes in tree order, with parent links; helper parts are appended as they arrive."""

    def __init__(self, snapshot_id, created, space=None):
        self.snapshot_id, self.created = snapshot_id, created
        self.nodes, self.order, self.kids = {}, [], {}  # keyed by stable id
        self.by_helper, self.places = {}, {}  # the helper's id -> stable id; identical siblings seen so far
        self.space = space or IdSpace()  # the window's ids, carried from one snapshot to the next
        self.anchors = {}  # stable id -> the id of its nearest named ancestor (or itself)
        self.before = None  # ids of the snapshot this one replaced, to tell what a click changed
        self.cursor = None  # the helper's cursor for the unread rest of the window, if any
        self.note = ""
        self.old_helper = False  # ids from a helper that predates cursors: it reads one 200-element part
        self.changed = False  # a resumed read found the page different: elements may be missing or repeated
        self.counts = None

    def add(self, items):
        for item in items:
            node = Node(item)
            if not node.id or node.id in self.by_helper or len(self.order) >= MAX_TREE:
                continue
            if self.order and not node.parent:
                node.parent = self.order[0]  # an older helper sends a flat list: hang it under the window
            else:
                node.parent = self.by_helper.get(node.parent)
            # A named element hangs off its nearest named ancestor, so unnamed wrappers that shift
            # (a new banner, a "Previous" item) do not renumber it; an unnamed one hangs off its parent.
            above = self.anchors.get(node.parent)
            base = above if named(node) else node.parent
            place = (base, fingerprint(node))
            self.places[place] = self.places.get(place, -1) + 1
            node.id = self.space.give(identity(base, node, self.places[place]))
            self.anchors[node.id] = node.id if named(node) else above
            self.by_helper[node.helper] = node.id
            self.nodes[node.id] = node
            self.order.append(node.id)
            self.kids.setdefault(node.parent, []).append(node.id)
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
        """The nearest named ancestors, outermost first; unnamed wrappers add nothing and are skipped."""
        names, node = [], self.nodes[ident]
        while node.parent in self.nodes and len(names) < depth:
            node = self.nodes[node.parent]
            if node.name or node.auto or node.type not in WRAPPERS:
                names.append(node.label())
        return " > ".join(reversed(names))

    def line(self, node, level=0, bounds=False, extra="", full=False, limit=LINE_NAME):
        """`id Type "name" ="value" [actions] flags`, indented by nesting level."""
        parts = [" " * min(level, LEVEL_CAP) + node.id, node.type]
        if node.name:
            parts.append('"' + (node.name if full else clip(node.name, limit)) + '"')
        elif node.auto:
            parts.append("#" + node.auto)
        if node.value:
            parts.append('="' + (node.value if full else clip(node.value, min(limit, LINE_VALUE))) + '"')
        if node.actions and node.actions != ("scroll_into_view",):
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
