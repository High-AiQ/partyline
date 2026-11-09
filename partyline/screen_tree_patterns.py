"""What a summary calls out so the common case is summary -> act: pagers and tables of similar rows."""
from collections import Counter

from .screen_tree import clip, fit

PAGER_WORDS = {"next", "previous", "prev", "older", "newer", "first", "last", ">", "<", "»", "«", "›", "‹"}
LINKS = {"Hyperlink", "Button"}
PAGER_NODES = 80  # a pager is a small subtree
MIN_ROWS = 4
SHOWN = 4  # repeated structures listed
PAGER_LINKS = 12
PATTERN_LINE = 200  # characters of one pattern line
PATTERN_BYTES = 900  # json bytes of all pattern lines in a summary


def descendants(tree, ident, limit):
    found, todo = [], list(tree.kids.get(ident, ()))
    while todo and len(found) < limit:
        node = tree.nodes[todo.pop(0)]
        found.append(node)
        todo.extend(tree.kids.get(node.id, ()))
    return found


def pagers(tree):
    """Small subtrees holding links named 1, 2, 3 (or next/previous): `{id: [(label, link id)]}`."""
    found, covered = {}, set()
    for ident in tree.order:
        if not tree.kids.get(ident) or tree.descendants()[ident] > PAGER_NODES:
            continue
        links = [node for node in descendants(tree, ident, PAGER_NODES) if node.type in LINKS and node.name]
        numbers = [node for node in links if node.name.isdigit()]
        if len(numbers) >= 2 or (numbers and any(node.name.lower() in PAGER_WORDS for node in links)):
            found[ident] = [(node.name, node.id) for node in links
                            if node.name.isdigit() or node.name.lower() in PAGER_WORDS][:PAGER_LINKS]
    for ident in found:
        node = tree.nodes[ident]
        while node.parent in tree.nodes:
            covered.add(node.parent)
            node = tree.nodes[node.parent]
    return {ident: links for ident, links in found.items() if ident not in covered}


def shape(tree, node):
    return node.type, tuple(sorted(Counter(kid.type for kid in tree.children(node.id)).items()))


def repeats(tree):
    """Parents whose children are mostly the same kind of row: `(parent, count, example)`."""
    found = []
    for ident in tree.order:
        kids = tree.children(ident)
        if len(kids) < MIN_ROWS:
            continue
        common, count = Counter(shape(tree, kid) for kid in kids).most_common(1)[0]
        if count >= MIN_ROWS and count * 2 > len(kids) and tree.descendants()[ident] > count * 2:
            example = next(kid for kid in kids if shape(tree, kid) == common)
            found.append((tree.nodes[ident], count, example))
    found.sort(key=lambda row: -tree.descendants()[row[0].id])
    return found[:SHOWN]


def describe(tree):
    """Lines for the summary: each pager with its link ids, each table of similar rows."""
    lines = []
    for ident, links in pagers(tree).items():
        node = tree.nodes[ident]
        lines.append(f"pager {node.label()} {node.id}: " + " ".join(
            f"{clip(name, 12)}={link}" for name, link in links))
    for parent, count, example in repeats(tree):
        sample = f' e.g. {example.id} "{clip(example.name, 50)}"' if example.name else f" e.g. {example.id}"
        lines.append(f"{count} similar {example.type} rows in {parent.label()} {parent.id}"
                     f" ({len(tree.kids.get(example.id, ()))} children each);{sample}")
    return fit([clip(line, PATTERN_LINE) for line in lines], str, budget=PATTERN_BYTES)[0]
