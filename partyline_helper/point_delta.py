"""Diff observations locally; only bounded changed rows cross the helper socket."""
import json
from collections import defaultdict, deque

FIELDS = ("control_type", "name", "value", "enabled", "selected", "toggle", "expand_state",
          "offscreen", "hidden", "focused")
KEEP = ("id", "parent", *FIELDS, "actions", "source", "provider_identity", "automation_id")
MAX_CHANGES, MAX_OPTIONS, MAX_BYTES = 20, 5, 128 * 1024


def row(item):
    return {key: item[key] for key in KEEP if key in item}


def partial(snapshot):
    return bool(snapshot.get("truncated") or snapshot.get("next_cursor") or snapshot.get("changed") or
                snapshot.get("captured_event_counter") != snapshot.get("event_counter"))


def align(old, new):
    """Pair path-bound UIA IDs by semantic identity and duplicate ordinal for comparison only.

    Provider identities remain authoritative. Remapped diagnostic rows use the real after ID;
    native dispatch still validates its unchanged runtime-and-path identity contract.
    """
    def key(item):
        return tuple(item.get(field) or "" for field in ("control_type", "name", "automation_id"))

    candidates = defaultdict(deque)
    for ident, item in old.items():
        if ident not in new and not item.get("provider_identity"):
            candidates[key(item)].append(ident)
    renamed = {}
    for ident, item in new.items():
        if ident not in old and not item.get("provider_identity") and (matches := candidates.get(key(item))):
            renamed[matches.popleft()] = ident
    if not renamed:
        return old
    return {renamed.get(ident, ident): {**item, "id": renamed.get(ident, ident),
                                      "parent": renamed.get(item.get("parent"), item.get("parent"))}
            for ident, item in old.items()}


def compact(before, after):
    if "elements" not in before or "elements" not in after:
        return {"compact": True, **{side: {"elements_unavailable": str(
            raw.get("elements_unavailable", "other observation unavailable"))[:160]}
            for side, raw in (("before", before), ("after", after))}}
    old = {item["id"]: item for item in before["elements"]}
    new = {item["id"]: item for item in after["elements"]}
    old = align(old, new)
    incomplete = partial(before) or partial(after)
    changed = [ident for ident, item in new.items() if ident not in old or any(
        item.get(key) != old[ident].get(key) for key in FIELDS)]
    if not incomplete:
        changed += [ident for ident in old if ident not in new]
    # A popup and its opener are more useful than the focus/layout noise around them.
    changed.sort(key=lambda ident: 0 if new.get(ident, {}).get("control_type") in ("List", "Menu") else
                 1 if old.get(ident, {}).get("expand_state") != new.get(ident, {}).get("expand_state") else 2)
    children = {}
    for item in new.values():
        if item.get("control_type") in ("ListItem", "MenuItem"):
            children.setdefault(item.get("parent"), []).append(item["id"])

    def packet(ids):
        result = {"compact": True, "more": sum(ident not in ids for ident in changed),
                  "options": {ident: len(children[ident]) for ident in ids if ident in children}}
        for side, raw, items in (("before", before, old), ("after", after, new)):
            metadata = ("snapshot_id", "source", "captured_event_counter", "event_counter")
            result[side] = {key: raw[key] for key in metadata if key in raw}
            result[side].update(elements=[row(items[ident]) for ident in ids if ident in items],
                                truncated=incomplete)
        return result

    ids = []
    result = packet(ids)
    for ident in changed[:MAX_CHANGES]:
        group = [ident, *children.get(ident, ())[:MAX_OPTIONS]]
        while group:
            candidate_ids = list(dict.fromkeys([*ids, *group]))
            candidate = packet(candidate_ids)
            # Match the session's default JSON escaping, including worst-case Unicode names.
            if len(json.dumps(candidate).encode()) <= MAX_BYTES:
                ids, result = candidate_ids, candidate
                break
            group.pop()  # shrink option samples before dropping the changed container itself
        if not group:
            break
    return result
