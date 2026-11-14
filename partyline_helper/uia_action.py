"""Validate a snapshot target in the selected window before invoking a UIA pattern."""
from .uia_identity import element_id
from .uia_force import HINT, check_force, legacy
from .uia_patterns import (PATTERN, WINDOW_ACTIONS, ActionRefused, check_argument, combo, refuse_state,
                           refuse_unsupported)

FALLBACK_NODES, FALLBACK_DEPTH = 1000, 20  # search bound when a target has no recorded path


def by_path(provider, target, path):
    """Walk the recorded child indices; the node must still carry the target identity."""
    node = provider.root()
    for index in path:
        if not provider.same_window(node):
            return None
        children = provider.children(node)
        if index >= len(children):
            return None
        node = children[index]
    if provider.same_window(node) and element_id(provider, node, path) == target:
        return node
    return None


def find(provider, target, path=None):
    if path is not None and (node := by_path(provider, target, path)) is not None:
        return node
    stack = [(provider.root(), 0, [])]
    visited = 0
    while stack and visited < FALLBACK_NODES:
        node, depth, path = stack.pop()
        visited += 1
        if not provider.same_window(node):
            continue
        if element_id(provider, node, path) == target:
            return node
        if depth < FALLBACK_DEPTH:
            children = provider.children(node)
            stack.extend((child, depth + 1, [*path, index])
                         for index, child in reversed(list(enumerate(children))))
    return None


def prepare(provider, target, action, arg=None, path=None, force=False):
    check_argument(action, arg)
    check_force(action, force)
    node = find(provider, target, path)
    if node is None or not provider.current():
        raise ActionRefused("stale or unknown element")
    props = provider.properties(node)
    provider.state(node, props)
    if not props.get("enabled") and not force:
        raise ActionRefused(HINT)
    is_window = target == element_id(provider, provider.root(), [])
    if action == "select" and combo(props) and not isinstance(arg, str):
        raise ActionRefused("select on a ComboBox requires value with the option name")
    if action == "select" and isinstance(arg, str) and not combo(props):
        raise ActionRefused("select value requires a ComboBox; select an option without value")
    named_select = action == "select" and combo(props) and isinstance(arg, str)
    fallback = force and not props.get("enabled") and legacy(props)
    if ((action != "press" and PATTERN[action] not in props.get("patterns", [])
         and not named_select and not fallback)
            or (action in WINDOW_ACTIONS and not is_window)):
        refuse_unsupported(action, props, is_window)
    if action == "set_value" and provider.password(node):
        raise ActionRefused("password fields cannot be set")
    if action == "set_value" and provider.read_only(node):
        raise ActionRefused("element is read-only")
    refuse_state(action, props, arg)
    return node, props
