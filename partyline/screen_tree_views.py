"""Small answers about a stored window tree: summary, ls, find and text."""
from collections import Counter

from .screen_tree import fit

OUTLINE_KIDS = 8  # children listed per region in the summary
OUTLINE_TYPES = 10
LIST_MAX = 5000  # nodes considered for one ls
LEAF_TEXT = 300  # characters of one text line shown
HINT = ("Explore with root=<id> (ls), query/control_type (find), text=true (page text), then act "
        "with screen_element_action; refresh=true takes a new snapshot.")


def counted(tree, node):
    kids = len(tree.kids.get(node.id, ()))
    return f"({kids} children, {tree.descendants()[node.id]} in all)" if kids else ""


def summary(tree):
    nodes = tree.nodes
    types = Counter(node.type for node in nodes.values())
    result = {"nodes": len(nodes), "types": ", ".join(f"{name} {count}"
                                                      for name, count in types.most_common(OUTLINE_TYPES))}
    document = first_document(tree)
    if document:
        result["document"] = tree.line(nodes[document])
    rows = []

    def region(parent_id, level, limit):
        """List a node's children at `level`; a web page's Document is opened two levels deeper."""
        while len(tree.kids.get(parent_id, ())) == 1 and tree.kids.get(tree.kids[parent_id][0]):
            parent_id = tree.kids[parent_id][0]  # skip a chain of single-child wrappers
        children = tree.children(parent_id)
        shown = [node for node in children if level <= 1 or tree.kids.get(node.id)][:OUTLINE_KIDS]
        for node in shown:
            rows.append((node, level))
            deeper = limit + 2 if node.type == "Document" else limit
            if level < deeper:
                region(node.id, level + 1, deeper)
        if shown and len(children) > len(shown):
            rows.append((len(children) - len(shown), level))

    for top in tree.kids.get(None, ())[:1]:
        rows.append((nodes[top], 0))
        region(top, 1, 2)

    def render(row):
        item, level = row
        if isinstance(item, int):
            return " " * level + f"… {item} more"
        return tree.line(item, level, extra=counted(tree, item))

    result["outline"], _ = fit(rows, render, budget=2400)
    return result


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


def terms(query):
    return [part.strip().lower() for part in (query or "").split("|") if part.strip()]


def find(tree, query, control_type, root, offset, bounds):
    ids = tree.subtree(root)
    if ids is None:
        return None
    wanted, kind = terms(query), (control_type or "").lower()
    rows = []
    for ident in ids:
        node = tree.nodes[ident]
        if kind and node.type.lower() != kind:
            continue
        text = f"{node.name}\n{node.value}".lower()
        if wanted and not any(term in text for term in wanted):
            continue
        rows.append(node)
    return page(tree, rows[offset:], offset,
                lambda node: tree.line(node, 0, bounds, "in: " + tree.path(node.id)), len(rows))


def text_lines(tree, root):
    """Visible text in reading order: Text nodes plus the names and values of leaf controls."""
    ids = tree.subtree(root)
    if ids is None:
        return None
    lines = []
    for ident in ids:
        node = tree.nodes[ident]
        leaf = not tree.kids.get(ident)
        if node.type == "Text" or (leaf and node.name):
            line = node.name
        elif node.type == "Edit" and node.value:
            line = f"[{node.name}] {node.value}".strip()
        else:
            continue
        if line and (not lines or lines[-1] != line):
            lines.append(line[:LEAF_TEXT])
    return lines


def first_document(tree):
    return next((ident for ident in tree.order if tree.nodes[ident].type == "Document"), None)


def text(tree, root, query, context, offset):
    scope = root if root is not None else first_document(tree)
    lines = text_lines(tree, scope)
    if lines is None:
        return None
    wanted = terms(query)
    if wanted:
        hits = [i for i, line in enumerate(lines) if any(term in line.lower() for term in wanted)]
        keep = sorted({j for i in hits for j in range(max(0, i - context), min(len(lines), i + context + 1))})
        rows = [index for index in keep if index >= offset]
        total = len(keep)
    else:
        rows, total = list(range(offset, len(lines))), len(lines)
    result = page(tree, rows, 0, lambda index: f"{index}: {lines[index]}".replace('"', "'"), len(rows),
                  starts=rows)  # a text offset is a line number, and hits skip lines
    result["total"] = total
    return result
