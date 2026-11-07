"""Summarize held-out JSONL responses (thresholds fixed before inspection)."""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / 'generated'


def percentile(values, p):
    values = sorted(values)
    return values[round((len(values) - 1) * p)] if values else float('nan')


def main():
    dataset = json.loads((OUT / 'dataset.json').read_text())
    journal = OUT / 'responses.jsonl'
    if not journal.exists():
        journal = ROOT / 'responses.jsonl'
    records = [json.loads(x) for x in journal.read_text().splitlines()]
    by_key = {x['key']: x for x in records if 'response' in x}
    choices = [r for r in dataset['choices'] if r['split'] == 'heldout']
    for arm in ('text', 'image'):
        entries = [(row, by_key[row['id'] + ':' + arm]) for row in choices
                   if row['id'] + ':' + arm in by_key]
        predictions = [(r, item, item['response']['answers'][0]) for r, item in entries]
        scored = [(r, item, a) for r, item, a in predictions if a['type'] == 'choice']
        accepted = [(r, item, a) for r, item, a in scored if a['choice'] != 'abstain']
        print('\n', arm, 'n', len(entries), 'accepted', len(accepted), 'correct',
              sum(a['choice'] == r['expected'] for r, _, a in accepted))
        print('latency p50/p95', *(round(percentile([x['seconds'] for _, x in entries], p)*1000)
                                    for p in (.5, .95)))
        print('confidence Brier all choices', statistics.mean(
            (a['confidence'] - (a['choice'] == r['expected'])) ** 2 for r, _, a in scored))
        for index in range(5):
            group = [(r, a) for r, _, a in scored if min(int(a['confidence'] * 5), 4) == index]
            print('reliability', index / 5, len(group),
                  round(statistics.mean(a['confidence'] for _, a in group), 3) if group else None,
                  sum(a['choice'] == r['expected'] for r, a in group))
        for threshold in (0, .5, .7, .8, .9, .95, .99):
            group = [(r, a) for r, _, a in accepted if a['confidence'] >= threshold]
            print('threshold', threshold, 'accepted', len(group), 'errors',
                  sum(a['choice'] != r['expected'] for r, a in group))
        pairs = [(a['choice'],
                  by_key[r['id'] + ':' + arm + ':permuted']['response']['answers'][0].get('choice'))
                 for r, _, a in scored if r['id'] + ':' + arm + ':permuted' in by_key]
        print('order changes', sum(a != b for a, b in pairs), '/', len(pairs))
    pairs = [r for r in dataset['verification'] if r['split'] == 'heldout']
    ver = [(r, by_key[r['id'] + ':verify']) for r in pairs if r['id'] + ':verify' in by_key]
    def success(v):
        return v['response']['answers'][0].get('probability', 0) >= .5

    print('\nverification n', len(ver), 'false successes',
          sum(r['label'] != 'success' and success(v) for r, v in ver),
          'non-success', sum(r['label'] != 'success' for r, _ in ver),
          'true successes', sum(r['label'] == 'success' and success(v) for r, v in ver))
    def deterministic(r):
        if r['after_note'] == 'Saved' and r['after'][0]['name'] == r['expected_field']:
            return 'success'
        if r['after_note'] == 'No change (no-op)':
            return 'failed'
        return 'unknown'

    print('deterministic correct', sum(deterministic(r) == r['label'] for r in pairs), '/', len(pairs))
    print('verification p50/p95 ms',
          *(round(percentile([v['seconds'] for _, v in ver], p)*1000) for p in (.5, .95)))
    usage = [r['response']['usage'] for r in records if 'response' in r]
    print('responses', len(records), 'tokens', sum(u['input_tokens'] for u in usage) + 162,
          'conservative total', sum(r['conservative_cost'] for r in records) + 162*.25/1e6)
    print('usage details', sum(u['input_tokens_details']['cached_tokens'] for u in usage),
          sum(u['input_tokens_details']['cache_write_tokens'] for u in usage))
    actor = json.loads((ROOT / 'actor-results.json').read_text())
    labels = {r['id']: r for r in choices}
    local = [r for r in actor['results'] if r['id'] in labels]
    accepted = [r for r in local if r['choice'] != 'abstain']
    print('local n', len(local), 'accepted', len(accepted), 'correct',
          sum(r['choice'] == labels[r['id']]['expected'] for r in accepted),
          'latency p50/p95 ms',
          *(round(percentile([r['seconds'] for r in local], p)*1000) for p in (.5, .95)))
    print('local load seconds', actor['load_seconds'], 'peak bytes', actor['peak_vram_bytes'])


if __name__ == '__main__':
    main()
