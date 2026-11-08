"""Validate a snapshot target in the selected window before invoking a UIA pattern."""
from .uia_identity import element_id
from .uia_snapshot import MAX_DEPTH, MAX_ELEMENTS


def find(provider, target):
    stack = [(provider.root(), 0, [])]
    visited = 0
    while stack and visited < MAX_ELEMENTS:
        node, depth, path = stack.pop()
        visited += 1
        if not provider.same_window(node):
            continue
        if element_id(provider, node, path) == target:
            return node
        if depth < MAX_DEPTH:
            children = provider.children(node)
            stack.extend((child, depth + 1, [*path, index])
                         for index, child in reversed(list(enumerate(children))))
    return None


def prepare(provider, target, action, value=None):
    if action not in ("invoke", "toggle", "set_value"):
        raise ValueError("unsupported action")
    if action == "set_value" and not isinstance(value, str):
        raise ValueError("set_value requires a text value")
    node = find(provider, target)
    if node is None or not provider.current():
        raise ValueError("stale or unknown element")
    props = provider.properties(node)
    if not props.get("enabled"):
        raise ValueError("element is disabled")
    pattern = {"invoke": "Invoke", "toggle": "Toggle", "set_value": "Value"}[action]
    if pattern not in props.get("patterns", []):
        raise ValueError("element does not support this action")
    if action == "set_value" and provider.password(node):
        raise ValueError("password fields cannot be set")
    if action == "set_value" and provider.read_only(node):
        raise ValueError("element is read-only")
    return node, props
