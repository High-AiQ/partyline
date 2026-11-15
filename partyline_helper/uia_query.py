"""Ask UIA for matching nodes, caching only matches and their control-view ancestors."""
import uuid
import re

from .timing import Timing
from .uia_snapshot import MAX_ELEMENTS, describe
from .uia_walk_parts import is_wrapper


def terms(query):
    """A substring superset of the server's query grammar; the server applies final anchors."""
    result = []
    for part in query.split('|'):
        part = part.strip().lower()
        whole = part.startswith('=')
        start, end = part.startswith('^'), part.endswith('$') and len(part) > 1
        part = part[1:] if whole or start else part
        part = part[:-1] if end and not whole else part
        result.append((part.strip() if whole else part, whole or start and end))
    return result


def condition(provider, query):
    automation = provider.automation
    conditions = []
    if query.get('query'):
        choices = []
        for word, whole in terms(query['query']):
            if not word and not whole:
                continue
            # Server names normalise quotes/control characters. A safe token is a superset
            # even when the original accessible name contains a newline or a double quote.
            if any(char.isspace() or char == "'" for char in word):
                word = max(re.split(r"[\s']+", word), key=len)
                whole = False
            choices.append(automation.CreatePropertyConditionEx(30005, word, 1 if whole else 3)
                           if word or whole else automation.CreateTrueCondition())
        if choices:
            combined = choices[0]
            for choice in choices[1:]:
                combined = automation.CreateOrCondition(combined, choice)
            conditions.append(combined)
    if query.get('control_type'):
        from .uia_windows import TYPES
        kind = next((ident for ident, name in TYPES.items()
                     if name.lower() == query['control_type'].lower()), None)
        if kind is None:
            return automation.CreateFalseCondition()
        conditions.append(automation.CreatePropertyCondition(30003, kind))
    if not conditions:
        return automation.CreateTrueCondition()
    return (conditions[0] if len(conditions) == 1 else
            automation.CreateAndCondition(*conditions))


def matches(provider, query):  # pragma: no cover - native calls exercised by Windows foundations
    wanted = provider.automation.CreateAndCondition(provider.automation.ControlViewCondition,
                                                     condition(provider, query))
    cache = provider.request(1)  # TreeScope_Element: descendants of matches are never prefetched
    for root in (provider.root(), *provider.popups()):
        found = root.FindAllBuildCache(7, wanted, cache)
        for index in range(min(found.Length, MAX_ELEMENTS + 1)):
            yield found.GetElement(index)


def snapshot(provider, query, frame=None, finder=matches):
    timing = Timing()
    rows, paths, known, children, positions = {}, {}, {}, {}, {}
    truncated, changed = False, False

    def locate(node, depth=0):
        if depth > 40 or not provider.same_window(node):
            raise ValueError('query target left the granted window')
        runtime = tuple(provider.runtime_id(node))
        if runtime in known:
            return known[runtime]
        root = provider.root()
        if runtime == tuple(provider.runtime_id(root)):
            path, parent_id = (), None
        else:
            if () not in children:
                children[()] = provider.children(root)
                positions[()] = {tuple(provider.runtime_id(child)): index
                                 for index, child in enumerate(children[()])}
            parent = root if runtime in positions[()] else provider.parent(node)
            parent_path, parent_id = locate(parent, depth + 1)
            if parent_path not in children:
                children[parent_path] = provider.children(parent)
                positions[parent_path] = {tuple(provider.runtime_id(child)): index
                                          for index, child in enumerate(children[parent_path])}
            index = positions[parent_path][runtime]
            path = (*parent_path, index)
        props = provider.properties(node)
        ident = parent_id
        if not path or not is_wrapper(props):
            props = describe(provider, node, list(path), props, frame, parent_id)
            ident = props['id']
            rows[path] = props
            paths[ident] = list(path)
        known[runtime] = (path, ident)
        return path, ident

    with timing.phase('walk_ms'):
        for index, node in enumerate(finder(provider, query)):
            if index >= MAX_ELEMENTS:
                truncated = True
                break
            try:
                locate(node)
            except Exception:  # navigation can remove a match or its control-view ancestors mid-walk
                changed = True
                continue
    timing.values.update(nodes=len(rows), com_calls=getattr(provider, 'com_calls', 0))
    runtimes = [[list(runtime), ident] for runtime, (_, ident) in known.items() if ident]
    result = {'elements': [rows[path] for path in sorted(rows)], 'paths': paths, 'runtimes': runtimes,
              'snapshot_id': uuid.uuid4().hex, 'truncated': truncated, 'scoped': True}
    if changed:
        result['changed'] = True
    return timing.finish(result)
