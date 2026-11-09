"""Pieces of the UIA walk: frame mapping, wrapper rule and path resolution."""
from .uia_identity import element_id

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


class Resolver:
    """Find nodes again by child-index path, remembering each parent's children for the whole read."""

    def __init__(self, provider):
        self.provider = provider
        self.nodes = {(): provider.root()}
        self.kids = {}

    def node(self, path):
        path = tuple(path)
        depth = len(path)
        while depth and path[:depth] not in self.nodes:
            depth -= 1
        for end in range(depth, len(path)):
            parent = self.nodes[path[:end]]
            if not self.provider.same_window(parent):
                return None
            if path[:end] not in self.kids:
                self.kids[path[:end]] = self.provider.children(parent)
            kids = self.kids[path[:end]]
            if path[end] >= len(kids):
                return None
            self.nodes[path[:end + 1]] = kids[path[end]]
        node = self.nodes[path]
        return node if self.provider.same_window(node) else None

    def children(self, path):
        path = tuple(path)
        if path not in self.kids:
            node = self.node(path)
            self.kids[path] = [] if node is None else self.provider.children(node)
        return self.kids[path]

    def intact(self, parents):
        """Parent paths from a saved walk whose node and child count are as when it stopped."""
        good = set()
        for path, ident, count, index, nxt in parents:
            node = self.node(path)
            if node is None or element_id(self.provider, node, path) != ident:
                continue
            kids = self.children(path)
            # same child count, and the next unread child is still the one that was next
            if len(kids) == count and index < len(kids) and element_id(
                    self.provider, kids[index], [*path, index]) == nxt:
                good.add(tuple(path))
        return good

    def verified(self, ident, path):
        node = self.node(path)
        return node if node is not None and element_id(self.provider, node, list(path)) == ident else None
