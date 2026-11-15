"""Compact point-action deltas using the window's ordinary, actionable element IDs."""
from .screen_tree import Snapshot, clean, clip
from .screen_tree_ids import IdSpace

FIELDS = ("name", "value", "enabled", "selected", "toggle", "expand_state", "offscreen", "hidden",
          "focused")
MAX_LINES = 20


def label(node):
    return f'[{node.id}] {node.type} "{clip(node.name, 80)}"'


def state(value):
    return clip(clean(str(value).lower() if isinstance(value, bool) else value), 80)


def observed(node, key):
    if key in ("focused", "offscreen"):
        return ("focused" if key == "focused" else "off") in node.flags
    return node.cached.get(key)


def delta(before, after):
    lines = []
    # Match by provider ID too: changing a label or value can change a UIA server fingerprint.
    old = {node.helper: node for node in before.nodes.values()}
    new = {node.helper: node for node in after.nodes.values()}
    partial = before.partial or after.partial
    for ident in after.order:
        node = after.nodes[ident]
        previous = old.get(node.helper) or before.nodes.get(ident)
        if previous is None:
            line = "appeared: " + label(node)
            if node.type in ("List", "Menu"):
                children = [child for child in after.children(node.id)
                            if child.type in ("ListItem", "MenuItem")]
                if children:
                    names = ", ".join(label(child) for child in children[:5])
                    line += f" ({len(children)} options: {names}" + (", …" if len(children) > 5 else "") + ")"
            lines.append(line)
        else:
            changes = [f"{key} {state(observed(previous, key))}→{state(observed(node, key))}"
                       for key in FIELDS if observed(previous, key) != observed(node, key)]
            if previous.type != node.type:
                changes.insert(0, f"control_type {previous.type}→{node.type}")
            if changes:
                lines.append("changed: " + label(node) + " " + ", ".join(changes))
    if not partial:
        lines += ["disappeared: " + label(node) for node in before.nodes.values()
                  if node.helper not in new and node.id not in after.nodes]
    shown, size = [], 0
    for line in lines[:MAX_LINES]:
        line = clip(line, 600)
        if size + len(line) > 4000:
            break
        shown.append(line)
        size += len(line) + 1
    if len(lines) > len(shown):
        shown.append(f"more: {len(lines) - len(shown)} additional changes; read screen_elements")
    if partial:
        shown.append("partial observation; missing elements do not prove disappearance")
    return "\n".join(shown) if shown else "no element changes observed"


def apply(hub, grant_id, result):
    observation = result.pop("point_observation", None)
    if not observation:
        return False
    space = hub.spaces.setdefault(grant_id, IdSpace())
    space.renew()
    trees = []
    for side in ("before", "after"):
        raw = observation[side]
        if "elements" not in raw:
            result["changes"] = "unavailable: " + str(raw.get("elements_unavailable", "observation failed"))
            return False
        tree = Snapshot(raw.get("snapshot_id"), hub.clock(), space)
        tree.add(raw["elements"])
        tree.cursor = raw.get("next_cursor")
        tree.changed = bool(raw.get("changed") or
                            raw.get("captured_event_counter") != raw.get("event_counter"))
        tree.note = "partial observation" if raw.get("truncated") else ""
        tree.event_counter = raw.get("captured_event_counter")
        tree.event_version = hub.change_versions.get(grant_id, 0)
        tree.sources = raw.get("event_sources_supported") is True
        tree.source = raw.get("source", "uia")
        trees.append(tree)
    result["changes"] = delta(*trees)
    result["changes_observed"] = any(result["changes"].startswith(prefix)
                                     for prefix in ("appeared:", "changed:", "disappeared:"))
    hub.remember(grant_id, trees[-1])
    return True
