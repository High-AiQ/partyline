"""Explicitly override a provider's disabled report, retaining observed evidence."""
from .uia_patterns import ActionRefused
from .uia_snapshot import MAX_TEXT

FORCE_ACTIONS = ("invoke", "toggle", "select", "expand")
HINT = "element is disabled; use force=true only when the person confirms the control is usable"


def legacy(props):
    return (props.get("control_type") in ("Hyperlink", "Button")
            and "LegacyIAccessible" in props.get("patterns", []))


def title(provider):
    try:
        return str(provider.properties(provider.root()).get("name", ""))[:MAX_TEXT]
    except Exception:
        return None


def forced_call(provider, node, action, arg, initial, check, call=None):
    def invoke():
        before = title(provider)
        method = "pattern"
        check()
        try:
            result = call() if call else provider.action_call(node, action, arg)()
        except Exception:
            check()
            if not legacy(initial) or not provider.same_window(node):
                raise
            provider.default_action(node)
            result, method = None, "LegacyIAccessible.DoDefaultAction"
        check()
        after = title(provider)
        observed = {"reported_disabled": True, "action_method": method,
                    "window_title_before": before, "window_title_after": after,
                    "window_title_changed": (before != after
                                             if before is not None and after is not None else None)}
        try:
            current = provider.properties(node)
            observed["focused_after"] = bool(current.get("focused"))
            observed["focus_changed"] = initial.get("focused") != current.get("focused")
            if "value" in initial and "value" in current:
                observed["value_changed"] = initial["value"] != current["value"]
        except Exception:
            observed["target_state_unavailable"] = True
        return {**(result if isinstance(result, dict) else {}), **observed}
    return invoke


def check_force(action, force):
    if not isinstance(force, bool) or (force and action not in FORCE_ACTIONS):
        raise ActionRefused("force is supported only for invoke, toggle, select and expand")
