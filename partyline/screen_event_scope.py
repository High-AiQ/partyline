"""Which captured subtrees UI Automation events came from, so a read or action judges only what it uses."""
from .screen_timing import phase
from .screen_tree import clip

UNPLACED = ("tree inconsistent: events during capture from elements this read did not list; read the "
            "whole window once (no query, root or id), then read with root=<id> or query=<name>")
SHOWN = 3  # busy subtrees and stable parts an answer names


def above(tree, ident):
    """The element and every ancestor in this tree, nearest first."""
    found = []
    while ident in tree.nodes and ident not in found:
        found.append(ident)
        ident = tree.nodes[ident].parent
    return found


def related(tree, first, second):
    """True when one element is the other or sits above it: an event at one touches the other's view."""
    return first in above(tree, second) or second in above(tree, first)


def outermost(tree, ids):
    return {ident for ident in ids if not ids.intersection(above(tree, ident)[1:])}


def stable_parts(tree, busy, limit=SHOWN * 2):
    """The largest subtrees that hold no busy element, in tree order: each one reads consistently."""
    if not tree.order or tree.order[0] in busy:
        return []
    covering = {ident for root in busy for ident in above(tree, root)} - set(busy)
    found, queue = [], [tree.order[0]]
    for ident in queue:
        for child in tree.kids.get(ident, ()):
            if child in busy:
                continue
            if child in covering:
                queue.append(child)
            elif len(found) < limit:
                found.append(child)
    return found


def busy_note(tree, roots):
    names = "; ".join(clip(tree.line(tree.nodes[root]), 80) for root in sorted(roots)[:SHOWN])
    more = f" and {len(roots) - SHOWN} more" if len(roots) > SHOWN else ""
    parts = stable_parts(tree, set(roots))
    advice = ("read a part without it: " + ", ".join(f"root={part}" for part in parts[:SHOWN])
              if parts else "read it again when it settles")
    return (f"busy subtree: {names}{more} kept changing while it was read, so what is listed under it may "
            f"be stale; everything outside it is consistent; {advice}")


class EventScope:
    async def events(self, principal, grant, device, tree):
        """`(moved, chains, unsure)`: events came after the capture began.

        Each chain is a source and its ancestors; `unsure` holds sources whose ancestry may be stale.
        `chains` is None when an event cannot be placed, which the caller must treat as touching everything.
        """
        fields = {"events_since": tree.event_counter} if getattr(tree, "sources", False) else {}
        with phase("barrier_ms"):
            status = await self.exchange(principal, grant, device, "read_window_elements",
                                         event_status=True, **fields)
        if status.get("event_counter") == tree.event_counter:
            return False, [], set()
        found = status.get("event_sources")
        if (not fields or not isinstance(found, dict) or found.get("overflow") or found.get("unplaced")
                or status.get("events_supported") is not True or status.get("subscription_live") is not True):
            return True, None, set()
        return True, found.get("ids", []), set(found.get("unsure", ()))

    async def judge(self, principal, grant, device, tree):
        """`(moved, roots)`: the outermost tree elements events since the capture began came from.

        A source this tree does not hold is ignored in a query's tree, which keeps matches only, and
        stands for its nearest listed ancestor in a whole-window tree. `roots` is None when events cannot
        be placed.
        """
        moved, chains, unsure = await self.events(principal, grant, device, tree)
        if chains is None:
            return moved, None
        ids = set()
        for chain in chains:
            held = chain[0] in tree.by_helper
            if not held and not tree.scoped and (tree.cursor or chain[0] in unsure):
                return True, None  # an unread part may hold it, or its ancestry is stale
            ident = next((tree.by_helper[helper] for helper in chain[:1 if tree.scoped else None]
                          if helper in tree.by_helper), None)
            if ident is not None:
                ids.add(ident)
            elif tree.cursor:
                return True, None
        return moved, outermost(tree, ids)

    async def target_stable(self, principal, grant, device, tree, ident):
        """No event came from the target, an ancestor or anything below it since the capture began."""
        if getattr(tree, "event_counter", None) is None or ident not in tree.nodes:
            return False
        moved, chains, unsure = await self.events(principal, grant, device, tree)
        if not moved:
            return True
        if chains is None:
            return False
        for chain in chains:
            source = tree.by_helper.get(chain[0])
            if source is None:
                if chain[0] in unsure or tree.cursor or tree.nodes[ident].helper in chain:
                    return False  # at or below the target without a node of its own, or unplaceable
            elif related(tree, source, ident):
                return False
        return True

    def scope_top(self, tree, options):
        """The element a read answers about; None when it answers about the whole captured tree."""
        if tree.scoped:
            return None
        for key in ("id", "root"):
            ident = options.get(key)
            if ident in tree.by_helper and ident not in tree.nodes:
                ident = tree.by_helper[ident]
            if ident in tree.nodes:
                return ident
        return None

    def busy_in(self, tree, top):
        """Busy roots that touch what is answered: all of them for a whole-tree answer."""
        return {root for root in tree.busy if top is None or related(tree, root, top)}
