"""Recompute committed results without network access; run with python -I."""
import hashlib
import json
import sys
from pathlib import Path


def main():
    if not sys.flags.isolated:
        raise SystemExit('Run with python -I')
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    from audit import inspect
    from corpus import load
    from evaluate import report
    from run import request, responses

    dataset, preflight = inspect(load(root / 'recorded-42484211467.json'), request)
    old = [json.loads(s) for s in (root.parent / 'decisions-pilot/responses.jsonl').read_text().splitlines()]
    study = [json.loads(s) for s in (root / 'responses.jsonl').read_text().splitlines()]
    predictions = responses(study)
    if set(predictions) != {r['id'] for r in dataset['choices']} or len(study) != len(predictions):
        raise ValueError('study journal does not exactly cover selected tasks')
    gate = json.loads((root / 'gate.json').read_text())
    result = report(dataset, predictions, gate)
    result.update(corpus_sha256=preflight['selected_dataset_digest'], gate=gate,
                  gate_file_sha256=hashlib.sha256((root / 'gate.json').read_bytes()).hexdigest(),
                  conservative_total_dollars=162 * .25 / 1_000_000 +
                  sum(r['conservative_cost'] for r in old + study))
    result['usage'] = {
        'responses': len(study), 'historical_records': len(old),
        'input_tokens': sum(r['response']['usage']['input_tokens'] for r in study),
        'cache_write_tokens': sum(r['response']['usage']['input_tokens_details']['cache_write_tokens']
                                  for r in study),
        'cache_read_tokens': sum(r['response']['usage']['input_tokens_details']['cached_tokens']
                                 for r in study),
        'output_tokens': sum(r['response']['usage']['output_tokens'] for r in study),
        'new_conservative_dollars': sum(r['conservative_cost'] for r in study),
        'historical_conservative_dollars': 162 * .25 / 1_000_000 +
        sum(r['conservative_cost'] for r in old),
        'models': sorted({r['response']['model'] for r in study})}
    result['latency_ms'] = {}
    for split in ('dev', 'heldout'):
        times = sorted(predictions[r['id']]['seconds'] * 1000 for r in dataset['choices']
                       if r['split'] == split)
        result['latency_ms'][split] = {name: times[round((len(times) - 1) * p)]
                                      for name, p in [('p50', .5), ('p95', .95)]}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
