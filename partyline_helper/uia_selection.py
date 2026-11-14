"""Dropdown selection and evidence of a UIA pattern's effect, without synthesized input."""
from .uia_action import FALLBACK_DEPTH, FALLBACK_NODES
from .uia_patterns import ActionRefused
from .uia_options import containers, identity

STATE = {"expand": "expand_state", "collapse": "expand_state", "toggle": "toggle",
         "select": "selected", "set_value": "value"}


def effect(action, before, after):
    key = STATE.get(action)
    if key is None:
        return {}
    if key not in before or key not in after:
        return {"effect": "unknown", "hint": "could not verify the pattern state"}
    changed = before[key] != after[key]
    result = {"effect": "changed" if changed else "none"}
    if not changed:
        result["hint"] = ("pick an option with select on the option element"
                          if before.get("control_type") == "ComboBox" else "pattern state did not change")
    return result


def option(provider, roots, name):
    stack, seen, matches = [(node, 0) for node in roots], set(), []
    while stack and len(seen) < FALLBACK_NODES:
        node, depth = stack.pop()
        if not provider.same_window(node):
            continue
        ident = tuple(provider.runtime_id(node))
        if ident in seen:
            continue
        seen.add(ident)
        props = provider.properties(node)
        if props.get("name") == name and "SelectionItem" in props.get("patterns", []):
            matches.append((node, props))
        if depth < FALLBACK_DEPTH:
            stack.extend((child, depth + 1) for child in provider.children(node))
    if len(matches) > 1:
        raise ActionRefused("option name is ambiguous; select an option element instead")
    return matches[0] if matches else None


def select_call(provider, node, name, before, check, force=False):
    def call():
        result = {}
        def act(target, action):
            check()
            if not provider.same_window(target):
                raise ActionRefused("stale or unknown element")
            provider.action_call(target, action, {})()

        previous = {identity(provider, item) for item in containers(provider, node)}
        if before.get("expand_state") != "expanded":
            act(node, "expand")
        try:
            provider.refresh()
            # Prefer the combo's own subtree. A separate popup is a sibling under the grant root.
            match = option(provider, [node], name)
            if match is None:
                roots = containers(provider, node)
                appeared = [item for item in roots if identity(provider, item) not in previous]
                match = option(provider, appeared, name) if appeared else None
                if match is None:
                    match = option(provider, roots, name)
            if match is None:
                raise ActionRefused("option not found; expand and read the popup options")
            target, props = match
            if not props.get("enabled") and not force:
                raise ActionRefused("option is disabled")
            provider.state(target, props)
            act(target, "select")  # SelectionItemPattern.Select, including on Chrome HTML options
            try:
                current = provider.properties(node)
            except Exception:  # selection may navigate away from the ComboBox itself
                current = {}
            changed = (before["value"] != current["value"]
                       if "value" in before and "value" in current else None)
            try:
                selected = provider.properties(target)
                provider.state(target, selected)
            except Exception:  # Chrome can dismiss and destroy the option immediately on selection
                selected = {}
            evidence = effect("select", props, selected)
            if changed is True:
                evidence = {"effect": "changed"}
            result.update(selected_option=name[:160], value_changed=changed, **evidence)
            return result
        finally:
            # Cleanup must never hide a successful Select or replace the original failure.
            try:
                act(node, "collapse")
            except Exception:
                result["collapse_failed"] = True
    return call
