"""Offline metrics; threshold selection reads development rows only."""
import math

from protocol import CASES, FAMILIES, SPLITS, digest, validate, verified

THRESHOLDS = (0, .5, .7, .8, .9, .95, .99, 1.01)


def upper_error(errors, n, alpha=.05):
    """One-sided exact binomial upper bound; trials are assumed independent."""
    if not n or errors == n:
        return 1.
    if not errors:
        return 1 - alpha ** (1 / n)

    def cdf(p):
        return sum(math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                            + k * math.log(p) + (n - k) * math.log1p(-p)) for k in range(errors + 1))
    low, high = errors / n, 1.
    for _ in range(60):
        mid = (low + high) / 2
        if cdf(mid) > alpha:
            low = mid
        else:
            high = mid
    return high


def answer(record):
    answers = record.get('response', {}).get('answers', [])
    a = answers[0] if len(answers) == 1 else {}
    confidence = a.get('confidence')
    if (a.get('type') != 'choice' or not isinstance(a.get('choice'), str) or
            not isinstance(confidence, (int, float)) or
            isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        return {'choice': 'abstain', 'confidence': 0}
    return a


def score(rows, responses, threshold=0, veto=True):
    accepted, errors, vetoes = 0, 0, 0
    for row in rows:
        a = answer(responses.get(row['id'], {}))
        if a['choice'] == 'abstain' or a['confidence'] < threshold:
            continue
        if veto and not validate(row, a['choice']):
            vetoes += 1
            continue
        accepted += 1
        errors += a['choice'] != row['expected']
    return {'total': len(rows), 'responses': sum(r['id'] in responses for r in rows),
            'accepted': accepted, 'errors': errors, 'vetoed': vetoes,
            'coverage': accepted / len(rows) if rows else 0,
            'selective_accuracy': 1 - errors / accepted if accepted else None,
            'error_upper_95': upper_error(errors, accepted)}


def choose_gate(rows, responses):
    dev = [r for r in rows if r['split'] == 'dev']
    if not dev or any(r['id'] not in responses for r in dev):
        raise ValueError('complete development responses required')
    # Predeclared rule: maximum coverage with zero dev errors and >=10 accepts.
    # If unsupported, freeze reject-all; never rescue it using held-out labels.
    candidates = [(t, score(dev, responses, t)) for t in THRESHOLDS]
    eligible = [(t, s) for t, s in candidates if s['errors'] == 0 and s['accepted'] >= 10]
    threshold = min(eligible, key=lambda x: (-x[1]['accepted'], x[0]))[0] if eligible else 1.01
    return {'schema': 1, 'threshold': threshold, 'dev_rows_hash': digest(dev),
            'dev_responses_hash': digest({r['id']: responses[r['id']] for r in dev}),
            'rule': 'max coverage, zero dev errors, minimum 10 accepts; else reject all',
            'dev_curve': [{'threshold': t, **s} for t, s in candidates]}


def check_dataset(dataset):
    if dataset.get('source') != 'recorded-windows-uia':
        raise ValueError('recorded Windows UIA evidence required')
    rows = dataset['choices']
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate task ids')
    for r in rows:
        if r['split'] != SPLITS[r['application']]:
            raise ValueError('application split changed')
        if r['case'] not in CASES or not r['snapshot'].get('elements'):
            raise ValueError('invalid task')
        if r['family'] != FAMILIES.get(r['application'], r['application']):
            raise ValueError('application family changed')
        if r['id'] != digest({k: v for k, v in r.items() if k != 'id'}):
            raise ValueError('task digest changed')
    families = [{r['family'] for r in rows if r['split'] == split} for split in ('dev', 'heldout')]
    if not families[0].isdisjoint(families[1]):
        raise ValueError('application family crosses split')


def report(dataset, responses, gate):
    check_dataset(dataset)
    dev_gate = choose_gate(dataset['choices'], responses)
    if gate != dev_gate:
        raise ValueError('frozen development gate or evidence changed')
    held = [r for r in dataset['choices'] if r['split'] == 'heldout']
    verification = [p for p in dataset['verification'] if p['split'] == 'heldout']
    negatives = [p for p in verification if p['label'] != 'success']
    false = sum(verified(p) for p in negatives)
    present = {r['case'] for r in held}
    return {'raw': score(held, responses, veto=False),
            'validator_only': score(held, responses),
            'gated': score(held, responses, gate['threshold']),
            'per_application': {app: score([r for r in held if r['application'] == app],
                                           responses, gate['threshold'])
                                for app, split in SPLITS.items() if split == 'heldout'},
            'per_case': {case: score([r for r in held if r['case'] == case],
                                    responses, gate['threshold']) for case in sorted(CASES)},
            'missing_heldout_cases': sorted(CASES - present),
            'verification': {'pairs': len(verification), 'non_success': len(negatives),
                             'false_success': false,
                             'independent_error_upper_95': None,
                             'predicate_labeled_successes': sum(
                                 p['label'] == 'success' for p in verification),
                             'predicate_transitions': sum(verified(p) for p in verification),
                             'warning': 'Circular labels and pre-dispatch refusal controls; '
                                        'zero false success is constructed, not robustness or recall'},
            'live_pilot_justified': False,
            'limitation': 'Small literal-intent corpus; task-level binomial bounds assume independence. '
                          'Controls in one application are correlated. '
                          'No application-level safety guarantee.'}
