"""Small answers about a stored window tree: summary, ls, find and text."""
from collections import Counter

from .screen_tree import clip, fit
from .screen_tree_patterns import MIN_ROWS, describe, shape
from .screen_tree_query import matcher

OUTLINE_KIDS = 8  # children listed per region in the summary
OUTLINE_ROWS = 2  # ... or just this many when they are rows of one shape
OUTLINE_NAME = 50
OUTLINE_TYPES = 10
LIST_MAX = 5000  # nodes considered for one ls
LEAF_TEXT = 500  # characters of one text line shown
CARRY_NODES = 200  # descendants checked for an item's own name before it is read out
RUN = 3  # unnamed siblings of one type shown as the first plus a count
NAMED_ITEMS = {"DataItem", "ListItem", "TreeItem", "TabItem", "MenuItem", "Button", "Hyperlink", "CheckBox",
               "RadioButton", "ComboBox", "Image", "HeaderItem", "SplitButton", "Custom"}
HINT = "ls root=<id>; find query/value/control_type; text=true; id=<id> reads one whole; then act."


def counted(tree, node):
    kids = len(tree.kids.get(node.id, ()))
    return f"({kids} children, {tree.descendants()[node.id]} in all)" if kids else ""


def summary(tree):
    nodes = tree.nodes
    types = Counter(node.type for node in nodes.values())
    result = {"nodes": len(nodes), "types": ", ".join(f"{name} {count}"
                                                      for name, count in types.most_common(OUTLINE_TYPES))}
    rows = []

    def region(parent_id, level, limit):
        """List a node's children at `level`; a web page's Document is opened two levels deeper."""
        while len(tree.kids.get(parent_id, ())) == 1 and tree.kids.get(tree.kids[parent_id][0]):
            parent_id = tree.kids[parent_id][0]  # skip a chain of single-child wrappers
        children = tree.children(parent_id)
        shown = collapse(tree, [node for node in children if level <= 1 or tree.kids.get(node.id)])
        rows_like = sum(shape(tree, node) == shape(tree, children[0]) for node in children) if children else 0
        rows_only = rows_like >= MIN_ROWS and rows_like * 2 > len(children)
        shown = shown[:OUTLINE_ROWS if rows_only else OUTLINE_KIDS]
        for node, same in shown:
            rows.append((node, level, f"+{same} alike" if same else ""))
            deeper = limit + 2 if node.type == "Document" else limit
            if level < deeper:
                region(node.id, level + 1, deeper)
        hidden = len(children) - sum(1 + same for _, same in shown)
        if shown and hidden > 0:
            rows.append((hidden, level, ""))

    for top in tree.kids.get(None, ())[:1]:
        rows.append((nodes[top], 0, ""))
        region(top, 1, 2)

    def render(row):
        item, level, same = row
        if isinstance(item, int):
            return " " * level + f"… {item} more"
        return tree.line(item, level, extra=" ".join(part for part in (counted(tree, item), same) if part),
                         limit=OUTLINE_NAME)

    result["outline"], _ = fit(rows, render, budget=2200)
    if lines := describe(tree):
        result["patterns"] = lines
    return result


def collapse(tree, nodes):
    """(node, extra like it that follow): runs of RUN+ unnamed siblings of one shape fold into the first."""
    def alike(one, other):
        return (one.type == other.type and not other.name and len(tree.kids.get(one.id, ())) == len(
            tree.kids.get(other.id, ())) and tree.descendants()[one.id] == tree.descendants()[other.id])

    out, index = [], 0
    while index < len(nodes):
        node, end = nodes[index], index + 1
        while not node.name and end < len(nodes) and alike(node, nodes[end]):
            end += 1
        out.append((node, end - index - 1 if end - index >= RUN else 0))
        index = end if end - index >= RUN else index + 1
    return out


def listing(tree, root, depth, offset):
    """Children of `root` (or grandchildren too), each with its own child count."""
    found = tree.subtree(root)
    if found is None:
        return None
    rows = []

    def walk(ident, level):
        for node in tree.children(ident):
            if len(rows) >= LIST_MAX:
                return
            rows.append((node, level))
            if level < depth:
                walk(node.id, level + 1)

    walk(root, 1)
    return page(tree, rows[offset:], offset, lambda row: tree.line(
        row[0], row[1] - 1, extra=counted(tree, row[0])), len(rows))


def page(tree, rows, offset, render, total, starts=None):
    """`starts[k]` is the offset that resumes after k rows; by default offset + k."""
    lines, shown = fit(rows, render)
    starts = starts if starts is not None else range(offset, offset + len(rows) + 1)
    result = {"lines": lines, "total": total, "resume": list(starts[:shown + 1])}
    if offset + shown < total:
        result.update(more=total - offset - shown, next_offset=starts[shown])
    return result


def find(tree, query, control_type, root, offset, bounds, value=None):
    ids = tree.subtree(root)
    if ids is None:
        return None
    by_name, by_value, kind = matcher(query), matcher(value), (control_type or "").lower()
    rows = []
    for ident in ids:
        node = tree.nodes[ident]
        if (kind and node.type.lower() != kind or by_name and not by_name(node.name)
                or by_value and not by_value(node.value)):
            continue
        rows.append(node)
    last = [None]

    def render(node):
        """`in:` names the ancestors of the lines after it, and is repeated only when they change."""
        path, head = tree.path(node.id), ""
        if path and path != last[0]:
            head = f"in: {path}\n"
        last[0] = path
        return head + tree.line(node, 0, bounds)

    return page(tree, rows[offset:], offset, render, len(rows))


def detail(tree, ident, bounds=False):
    """One element whole, like `cat`: full name and value, where it sits and how many children it has."""
    node = tree.nodes.get(ident)
    if node is None:
        return None
    text = tree.line(node, 0, bounds, counted(tree, node), full=True)
    if path := tree.path(ident):
        text += f"\nin: {path}"
    return page(tree, [node], 0, lambda _: text, 1)


def changes(tree, offset=0):
    """What a new snapshot has that the one before did not: the topmost new elements, and the counts."""
    before = tree.before or set()
    added = [ident for ident in tree.order if ident not in before]
    fresh = set(added)
    tops = [tree.nodes[ident] for ident in added if tree.nodes[ident].parent not in fresh]
    body = page(tree, tops[offset:], offset, lambda node: tree.line(node, 0, extra=counted(tree, node)),
                len(tops))
    body["diff"] = f"+{len(added)} -{len(before - set(tree.nodes))}"
    return body


def spoken(tree, ident):
    """The line a screen reader gives for one node, or None."""
    node = tree.nodes[ident]
    if node.type == "Text" or (not tree.kids.get(ident) and node.name):
        return node.name
    if node.type == "Edit" and node.value:
        return f"[{node.name}] {node.value}".strip()
    return None


def carried(tree, ident, name):
    """Whether text below `ident` already says `name` (looking at CARRY_NODES descendants at most)."""
    todo, seen = list(tree.kids.get(ident, ())), 0
    while todo and seen < CARRY_NODES:
        child, seen = todo.pop(), seen + 1
        if (line := spoken(tree, child)) and name in line:
            return True
        todo.extend(tree.kids.get(child, ()))
    return False


def text_lines(tree, root):
    """Visible text in reading order: Text nodes, leaf controls, and the names of items whose own text
    does not carry their accessible name (a row named "Book in X Title" with only "X" inside)."""
    ids = tree.subtree(root)
    if ids is None:
        return None
    lines = []
    for ident in ids:
        node = tree.nodes[ident]
        line = spoken(tree, ident)
        if line is None and node.name and node.type in NAMED_ITEMS and not carried(tree, ident, node.name):
            line = node.name
        if line and (not lines or lines[-1] != line):
            lines.append(clip(line, LEAF_TEXT))
    return lines


def first_document(tree):
    return next((ident for ident in tree.order if tree.nodes[ident].type == "Document"), None)


def text(tree, root, query, context, offset):
    scope = root if root is not None else first_document(tree)
    lines = text_lines(tree, scope)
    if lines is None:
        return None
    wanted = matcher(query)
    if wanted:
        hits = [i for i, line in enumerate(lines) if wanted(line)]
        keep = sorted({j for i in hits for j in range(max(0, i - context), min(len(lines), i + context + 1))})
        rows = [index for index in keep if index >= offset]
        total = len(keep)
    else:
        rows, total = list(range(offset, len(lines))), len(lines)
    result = page(tree, rows, 0, lambda index: f"{index}: {lines[index]}".replace('"', "'"), len(rows),
                  starts=rows)  # a text offset is a line number, and hits skip lines
    result["total"] = total
    return result
