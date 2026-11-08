"""No-network corpus selection and spending preflight; input is JSON data only."""
import json
from collections import Counter

from protocol import CASES, CASE_LIMITS, SPLITS, digest, validate

RATE = .25 / 1_000_000  # Same conservative input rate as the historical ledger.


def complete(snapshot):
    return bool(snapshot.get('elements') and snapshot.get('snapshot_id') and
                snapshot.get('truncated') is False and 'elements_unavailable' not in snapshot)


def snapshots(value):
    found = {}

    def walk(item):
        if isinstance(item, dict):
            if 'snapshot_id' in item:
                ident = item['snapshot_id']
                if ident in found and found[ident] != item:
                    raise ValueError('conflicting snapshot identity')
                found[ident] = item
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return found


def cap_rows(rows):
    counts, kept = Counter(), []
    for row in rows:
        key = row['application'], row['case']
        if counts[key] < CASE_LIMITS[row['case']]:
            kept.append(row)
            counts[key] += 1
    return kept


def inspect(dataset, request_builder):
    """Exclude an app with any incomplete read, before looking at predictions."""
    applications, excluded = [], set()
    for app in dataset['applications']:
        reads = snapshots(app)
        incomplete = not complete(app.get('before', {})) or any(not complete(s) for s in reads.values())
        if incomplete:
            excluded.add(app['application'])
        applications.append({
            'application': app['application'], 'split': SPLITS[app['application']],
            'snapshots': len(reads),
            'elements_per_snapshot': [len(s.get('elements', [])) for s in reads.values()],
            'truncated_snapshots': sum(s.get('truncated') is True for s in reads.values()),
            'incomplete': incomplete,
            'edit_actions': [{'label': p['label'], 'result': p.get('action_result', {}),
                              'predicate': p['predicate']}
                             for p in app.get('verification', []) if p['kind'] == 'set_value']})
    selected = cap_rows([r for r in dataset['choices'] if r['application'] not in excluded])
    verification = [p for p in dataset['verification'] if p['application'] not in excluded]
    effective = {**dataset, 'choices': selected, 'verification': verification}
    splits = {}
    for split in ('dev', 'heldout'):
        original = [r for r in dataset['choices'] if r['split'] == split]
        rows = [r for r in selected if r['split'] == split]
        sizes = [len(json.dumps(request_builder(r)).encode()) for r in rows]
        # Planning envelope, not a tokenizer measurement or invoice: allow two
        # tokens per serialized byte plus 4096 framing tokens per request.
        tokens = sum(2 * size + 4096 for size in sizes)
        splits[split] = {
            'original_rows': len(original), 'original_cases': dict(Counter(r['case'] for r in original)),
            'selected_rows': len(rows), 'selected_cases': dict(Counter(r['case'] for r in rows)),
            'missing_cases': sorted(CASES - {r['case'] for r in rows}),
            'maximum_correct_accepts': sum(r['expected'] != 'abstain' and validate(r, r['expected'])
                                           for r in rows),
            'serialized_request_bytes': sum(sizes), 'maximum_request_bytes': max(sizes, default=0),
            'planning_input_tokens': tokens, 'planning_cost_dollars': tokens * RATE}
    return effective, {
        'source_dataset_digest': digest(dataset), 'selected_dataset_digest': digest(effective),
        'applications': applications, 'excluded_applications': sorted(excluded),
        'case_limits_per_application': CASE_LIMITS, 'splits': splits,
        'planning_cost_dollars': sum(s['planning_cost_dollars'] for s in splits.values()),
        'verification_warning': 'Labels reuse the scored predicate; refused unknown ids never reach UIA. '
                                'Zero false success is constructed, not independent validation.'}
