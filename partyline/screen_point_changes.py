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


def options(tree, node, counts):
    if node.type not in ("List", "Menu"):
        return ""
    children = [child for child in tree.children(node.id) if child.type in ("ListItem", "MenuItem")]
    if not children:
        return ""
    names = ", ".join(label(child) for child in children[:5])
    count = counts.get(node.helper, len(children))
    more = ", …" if count > min(len(children), 5) else ""
    return f" ({count} options: {names}{more})"


def delta(before, after, option_counts=None):
    lines = []
    option_counts = option_counts or {}
    # Match by provider ID too: changing a label or value can change a UIA server fingerprint.
    old = {node.helper: node for node in before.nodes.values()}
    new = {node.helper: node for node in after.nodes.values()}
    partial = before.partial or after.partial
    for ident in after.order:
        node = after.nodes[ident]
        previous = old.get(node.helper) or before.nodes.get(ident)
        if previous is None:
            lines.append("appeared: " + label(node) + options(after, node, option_counts))
        else:
            changes = [f"{key} {state(observed(previous, key))}→{state(observed(node, key))}"
                       for key in FIELDS if observed(previous, key) != observed(node, key)]
            if previous.type != node.type:
                changes.insert(0, f"control_type {previous.type}→{node.type}")
            if changes:
                lines.append("changed: " + label(node) + " " + ", ".join(changes) +
                             options(after, node, option_counts))
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
        if observation.get("compact"):
            tree.scoped, tree.scope = True, {"point_delta": True}
            previous = trees[-1] if trees else getattr(hub, "snapshots", {}).get(grant_id)
            tree.retain_actions(previous)
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
    result["changes"] = delta(*trees, observation.get("options"))
    if observation.get("more"):
        result["changes"] += f"\nmore: {observation['more']} additional changes; read screen_elements"
    result["changes_observed"] = any(result["changes"].startswith(prefix)
                                     for prefix in ("appeared:", "changed:", "disappeared:"))
    if observation.get("compact") and not any(tree.partial for tree in trees):
        for node in trees[0].nodes.values():
            if node.helper not in trees[-1].by_helper:
                trees[-1].action_ids.pop(node.id, None)
                trees[-1].prior_helpers.pop(node.helper, None)
    hub.remember(grant_id, trees[-1])
    return True
