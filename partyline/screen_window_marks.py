"""The elements of a window's latest read that a marked snapshot numbers, and the geometry it keeps."""
from collections import OrderedDict

from .point_geometry import GeometryError, clean

MAX_MARKS = 60  # numbered boxes on one picture; more would hide what they point at
KEPT = 8  # snapshots per window a later click may still name
NO_TREE = "no screen_elements read of this window yet, so no numbered boxes; read it first, then repeat"
USE = ("x and y are pixels of this image, (0, 0) at its top left; pass this snapshot id to "
       "screen_window_click. Prefer screen_element_action; click a point only when elements cannot")


def mark_inputs(tree, limit=MAX_MARKS):
    """Boxes for the numbered marks, in tree order, actionable elements first. Screen pixels for UIA nodes,
    CSS pixels of the page viewport for Chrome pages; the helper converts either onto the image."""
    found = []
    for ident in tree.order:
        node = tree.nodes[ident]
        box, kind = node.bounds, "screen"
        if not box and node.cached.get("viewport_bounds"):
            box, kind = node.cached["viewport_bounds"], "viewport"
        if "off" in node.flags or not box or len(box) != 4 or not (node.actions or node.name):
            continue
        found.append((bool(node.actions), {"id": node.id, "name": node.name[:60],
                                           kind: [round(value) for value in box]}))
    chosen = [item for acted, item in found if acted] + [item for acted, item in found if not acted]
    chosen = chosen[:limit]
    order = {id(item): index for index, (_, item) in enumerate(found)}
    chosen.sort(key=lambda item: order[id(item)])
    return [{"n": number, **item} for number, item in enumerate(chosen, 1)]


def clean_marks(marks):
    """What the helper reported, cut to {n, id, name, box} with whole numbers."""
    result = []
    for mark in marks if isinstance(marks, list) else ():
        box = mark.get("box") if isinstance(mark, dict) else None
        if (isinstance(box, list) and len(box) == 4 and all(isinstance(v, int) for v in box)
                and isinstance(mark.get("n"), int)):
            result.append({"n": mark["n"], "id": str(mark.get("id", ""))[:128],
                           "name": str(mark.get("name", ""))[:60], "box": box})
    return result[:MAX_MARKS]


class Geometries:
    """Per window grant, the geometry of its last few snapshots; gone with the grant."""

    def __init__(self):
        self.table = {}

    def keep(self, grant_id, snapshot_id, data):
        try:
            geometry = clean(data)
        except GeometryError:
            return False
        if not isinstance(snapshot_id, str) or not 0 < len(snapshot_id) <= 64:
            return False
        rows = self.table.setdefault(grant_id, OrderedDict())
        rows[snapshot_id] = geometry
        while len(rows) > KEPT:
            rows.popitem(last=False)
        return True

    def get(self, grant_id, snapshot_id):
        return self.table.get(grant_id, {}).get(snapshot_id)

    def end(self, grant_id):
        self.table.pop(grant_id, None)
