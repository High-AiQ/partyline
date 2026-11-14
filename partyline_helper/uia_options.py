"""Find dropdown lists near their opener, including sibling Lists and owned popup roots."""
from .uia_action import FALLBACK_NODES
from .uia_patterns import combo


def identity(provider, node):
    return tuple(provider.runtime_id(node))


def containers(provider, node):
    """Nearest siblings first, with bounded depth/visits and no walk of unrelated windows."""
    found, seen, above, visits = [], set(), node, 0
    roots = [node]
    popups = provider.popups()
    boundaries = {identity(provider, provider.root()), *(identity(provider, item) for item in popups)}
    for _ in range(8):
        if identity(provider, above) in boundaries:
            break  # never climb from a granted or popup root into the desktop
        parent = provider.parent(above)
        if parent is None or not provider.same_window(parent):
            break
        roots.append(parent)
        above = parent
    roots.extend(popups)
    for root in roots:
        stack = [(root, 0)]
        while stack and visits < FALLBACK_NODES:
            visits += 1
            current, depth = stack.pop()
            if not provider.same_window(current):
                continue
            ident = identity(provider, current)
            if ident in seen:
                continue
            # Nodes at the depth boundary can be revisited from a nearer ancestor later.
            if depth < 4:
                seen.add(ident)
            if provider.option_container(current):
                found.append(current)
                continue  # don't scan thousands of options in a List to discover its container
            if depth < 4:
                stack.extend((child, depth + 1) for child in reversed(provider.children(current)))
    unique = {}
    for current in found:
        unique.setdefault(identity(provider, current), current)
    return list(unique.values())


def choices(provider, roots):
    names, seen, stack = [], set(), [(node, 0) for node in roots]
    while stack and len(seen) < FALLBACK_NODES:
        node, depth = stack.pop()
        if not provider.same_window(node):
            continue
        ident = identity(provider, node)
        if ident in seen:
            continue
        seen.add(ident)
        props = provider.properties(node)
        if "SelectionItem" in props.get("patterns", []):
            names.append(str(props.get("name", ""))[:160])
        if depth < 20:
            stack.extend((child, depth + 1) for child in provider.children(node))
    return names


def expand_call(provider, node, initial):
    """A provider may keep reporting Collapsed while its sibling option List is visible."""
    if not combo(initial):
        return provider.action_call(node, "expand", {})
    before = {identity(provider, item) for item in containers(provider, node)}
    call = provider.action_call(node, "expand", {})
    def invoke():
        call()
        provider.refresh()
        roots = containers(provider, node)
        names = choices(provider, roots)
        if not names:
            return {}
        appeared = any(identity(provider, item) not in before for item in roots)
        return {"options_found": len(names), "option_names": [name[:60] for name in names[:8]],
                "options_appeared": appeared}
    return invoke
