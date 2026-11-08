"""Frozen application split, task construction and deterministic offline vetoes."""
import hashlib
import json
from collections import Counter

from partyline_helper.uia_patterns import PATTERN, WINDOW_ACTIONS, argument, check_argument

SPLITS = {'notepad': 'dev', 'calculator': 'dev', 'tk': 'dev', 'charmap': 'heldout',
          'winforms': 'heldout', 'open-dialog': 'heldout', 'save-dialog': 'heldout'}
# Dialogs and fixtures share a host/toolkit; keep the entire family held out.
FAMILIES = {'open-dialog': 'winforms', 'save-dialog': 'winforms'}
CASES = {'normal', 'absent', 'duplicate', 'disabled', 'offscreen', 'wrong-pattern', 'stale'}
CASE_LIMITS = {case: 12 if case == 'normal' else 4 if case in ('disabled', 'offscreen') else 1
               for case in sorted(CASES)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def label(element):
    return f"{element['control_type']} named {element['name']!r}"


def tasks(application, before, current=None):
    """Ground labels in recorded properties; never alter or invent snapshot elements.

    Intents are deliberately literal. This is an initial UIA grounding test, not a
    test of open-ended user language. Missing case coverage is reported, not filled.
    """
    elements = before.get('elements', [])
    counts = Counter((e['control_type'], e['name']) for e in elements)
    rows = []

    def add(case, intent, action, target=None):
        if sum(r['case'] == case for r in rows) >= CASE_LIMITS[case]:
            return
        row = {'application': application, 'family': FAMILIES.get(application, application),
               'split': SPLITS[application], 'case': case, 'intent': intent,
               'snapshot': before, 'current': current if case == 'stale' else before,
               'action': action, 'expected': 'abstain' if target is None else target['id'] + ':' + action}
        row['id'] = digest(row)
        rows.append(row)

    add('absent', 'Invoke the Button named "PARTYLINE ABSENT 8f743b2e".', 'invoke')
    for e in elements:
        if not e.get('name') or e['control_type'] in ('Window', 'Pane'):
            continue
        unique = counts[(e['control_type'], e['name'])] == 1
        supported = [a for a in e.get('actions', []) if a not in WINDOW_ACTIONS]
        action = next((a for a in ('invoke', 'toggle', 'select', 'expand') if a in supported), None)
        if action and unique:
            case = 'disabled' if not e.get('enabled') else 'offscreen' if e.get('offscreen') else 'normal'
            if case != 'normal' or sum(r['case'] == 'normal' for r in rows) < 12:
                add(case, f"Use {action} on the {label(e)}.", action, e if case == 'normal' else None)
        if action and not unique and not any(r['case'] == 'duplicate' for r in rows):
            add('duplicate', f"Use {action} on the {label(e)}; no disambiguation is available.", action)
        if unique and 'toggle' not in e.get('actions', []) and not any(
                r['case'] == 'wrong-pattern' for r in rows):
            add('wrong-pattern', f"Toggle the {label(e)} using the Toggle pattern.", 'toggle')
    if current and current.get('snapshot_id') != before.get('snapshot_id'):
        target = next((r for r in rows if r['case'] == 'normal'), None)
        if target:
            add('stale', target['intent'], target['action'])
    return rows


def options(row):
    # Include incompatible pairs: otherwise the choice schema would do the
    # wrong-pattern test for the model. The validator must veto those pairs.
    return {e['id'] + ':' + row['action']: {'element_id': e['id'], 'action': row['action']}
            for e in row['snapshot']['elements']}


def validate(row, choice):
    if choice == 'abstain':
        return False
    presented, current = row['snapshot'], row['current']
    if (presented.get('truncated') or current.get('truncated') or
            presented.get('snapshot_id') != current.get('snapshot_id')):
        return False
    pair = options(row).get(choice)
    if not pair:
        return False
    matches = [e for e in current.get('elements', []) if e['id'] == pair['element_id']]
    if len(matches) != 1:
        return False
    e, action = matches[0], pair['action']
    if not e.get('enabled') or e.get('offscreen') or action not in e.get('actions', []):
        return False
    if PATTERN.get(action) not in e.get('patterns', []):
        return False
    try:
        check_argument(action, argument(pair))
    except ValueError:
        return False
    return sum((x['name'], x['control_type']) == (e['name'], e['control_type'])
               for x in current['elements']) == 1


def predicate(snapshot, expected):
    """Require one identified control with every requested UIA property equal."""
    if snapshot.get('truncated') or 'elements_unavailable' in snapshot:
        return False
    matches = [e for e in snapshot.get('elements', []) if e['id'] == expected['element_id']]
    return len(matches) == 1 and all(matches[0].get(k) == v for k, v in expected['equals'].items())


def verified(pair):
    # A postcondition already true before dispatch cannot establish completion.
    before, expected = pair['before'], pair['predicate']
    if before.get('truncated') or 'elements_unavailable' in before:
        return False
    controls = [e for e in before.get('elements', []) if e['id'] == expected['element_id']]
    if len(controls) != 1 or not all(k in controls[0] for k in expected['equals']):
        return False
    return not predicate(before, expected) and predicate(pair['after'], expected)
