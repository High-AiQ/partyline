"""No-network research integrity tests. Run through scripts/capped-test."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import evaluate
import protocol
import run


def element(ident='e1', name='Apply', **changes):
    return {'id': ident, 'name': name, 'control_type': 'Button', 'enabled': True,
            'offscreen': False, 'patterns': ['Invoke'], 'actions': ['invoke'], **changes}


def snapshot(elements=None, ident='s1'):
    return {'snapshot_id': ident, 'elements': elements or [element()], 'truncated': False}


def response(choice, confidence=.95):
    return {'response': {'answers': [{'type': 'choice', 'choice': choice, 'confidence': confidence}]}}


class ProtocolTests(unittest.TestCase):
    def test_cases_come_from_real_properties_without_mutating_evidence(self):
        before = snapshot([element(), element('e2', 'Duplicate'), element('e3', 'Duplicate'),
                           element('e4', 'Disabled', enabled=False),
                           element('e5', 'Outside', offscreen=True)])
        original = copy.deepcopy(before)
        rows = protocol.tasks('winforms', before, snapshot(ident='s2'))
        self.assertEqual(protocol.CASES, {r['case'] for r in rows})
        self.assertEqual(original, before)
        normal = next(r for r in rows if r['case'] == 'normal')
        self.assertEqual(normal['expected'], 'e1:invoke')
        self.assertEqual(normal['current']['snapshot_id'], before['snapshot_id'])
        self.assertTrue(protocol.validate(normal, 'e1:invoke'))
        for r in rows:
            if r['case'] != 'normal':
                self.assertEqual(r['expected'], 'abstain')
                for option in protocol.options(r):
                    # Wrong-pattern/disabled tasks may still name a different
                    # compatible control; correctness, not veto, catches that.
                    if r['case'] in ('stale', 'duplicate'):
                        if option.startswith('e2:') or r['case'] == 'stale':
                            self.assertFalse(protocol.validate(r, option))

    def test_vetoes_unknown_disabled_offscreen_pattern_duplicate_and_stale(self):
        row = protocol.tasks('notepad', snapshot())[1]
        for change in ({'enabled': False}, {'offscreen': True}, {'patterns': []}, {'actions': []}):
            bad = copy.deepcopy(row)
            bad['current']['elements'][0].update(change)
            self.assertFalse(protocol.validate(bad, 'e1:invoke'))
        self.assertFalse(protocol.validate(row, 'unknown:invoke'))
        self.assertFalse(protocol.validate(row, 'e1:toggle'))
        for field, value in (('truncated', True), ('snapshot_id', 'new')):
            bad = copy.deepcopy(row)
            bad['current'] = copy.deepcopy(bad['snapshot'])
            bad['current'][field] = value
            self.assertFalse(protocol.validate(bad, 'e1:invoke'))
        bad = copy.deepcopy(row)
        bad['current']['elements'].append(element('e2'))
        self.assertFalse(protocol.validate(bad, 'e1:invoke'))

    def test_frozen_gate_does_not_use_heldout_labels_or_responses(self):
        dev = []
        for index in range(10):
            r = copy.deepcopy(protocol.tasks('notepad', snapshot())[1])
            r['id'] = str(index)
            dev.append(r)
        held = protocol.tasks('charmap', snapshot())
        responses = {r['id']: response(r['expected'], .8) for r in dev}
        gate = evaluate.choose_gate(dev + held, responses)
        self.assertEqual(gate['threshold'], 0)
        altered = copy.deepcopy(held)
        for r in altered:
            r['expected'] = 'corrupt-label'
            responses[r['id']] = response('wrong', 1)
        self.assertEqual(gate, evaluate.choose_gate(dev + altered, responses))
        responses.pop('0')
        with self.assertRaisesRegex(ValueError, 'complete development'):
            evaluate.choose_gate(dev + held, responses)

    def test_no_supported_threshold_freezes_reject_all(self):
        rows = protocol.tasks('notepad', snapshot())
        responses = {r['id']: response('e1:invoke') for r in rows}
        self.assertEqual(evaluate.choose_gate(rows, responses)['threshold'], 1.01)

    def test_metrics_and_exact_bounds(self):
        rows = protocol.tasks('charmap', snapshot())
        responses = {r['id']: response('e1:invoke') for r in rows}
        raw = evaluate.score(rows, responses, veto=False)
        self.assertEqual((raw['accepted'], raw['errors']), (len(rows), len(rows) - 1))
        self.assertAlmostEqual(evaluate.upper_error(0, 59), 1 - .05 ** (1 / 59))
        self.assertAlmostEqual(evaluate.upper_error(1, 2), .97467943448)
        self.assertEqual(evaluate.upper_error(0, 0), 1)
        for record in ({}, response('e1:invoke', float('nan')), response('e1:invoke', True)):
            self.assertEqual(evaluate.answer(record)['choice'], 'abstain')

    def test_verification_needs_transition_and_complete_after_tree(self):
        before = snapshot([element(value='before')])
        after = snapshot([element(value='done')], 's2')
        pair = {'before': before, 'after': after,
                'predicate': {'element_id': 'e1', 'equals': {'value': 'done'}}}
        self.assertTrue(protocol.verified(pair))
        pair['before'] = after
        self.assertFalse(protocol.verified(pair))
        pair['before'], pair['after'] = before, before
        self.assertFalse(protocol.verified(pair))
        pair['after'] = {**after, 'truncated': True}
        self.assertFalse(protocol.verified(pair))
        # Even a matching after value cannot prove a transition from unavailable evidence.
        pair['before'], pair['after'] = {'elements_unavailable': 'timeout'}, after
        self.assertFalse(protocol.verified(pair))

    def test_evidence_excludes_ground_truth_and_has_incompatible_choices(self):
        row = next(r for r in protocol.tasks('winforms', snapshot()) if r['case'] == 'wrong-pattern')
        body = run.request(row)
        evidence = body['input'][0]['content'][0]['data']
        self.assertEqual(set(evidence), {'intent', 'snapshot', 'latest_snapshot_id'})
        self.assertIn('e1:toggle', {c['value'] for c in body['questions'][0]['choices']})
        self.assertFalse(protocol.validate(row, 'e1:toggle'))

    def test_journal_reuses_history_and_never_retries_uncertain_call(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(run, 'STATE', Path(directory)):
            harness = run.historical_harness()
            self.assertEqual(harness.STOP, 4.50)
            self.assertEqual(harness.MAX_REQUEST_RESERVE, .50)
            records = harness.records()
            self.assertGreater(len(records), 1000)
            pending = Path(directory) / 'pending.json'
            pending.write_text('{}')
            with patch.object(harness.urllib.request, 'urlopen') as network:
                with self.assertRaisesRegex(RuntimeError, 'Uncertain'):
                    harness.call('test', {})
                network.assert_not_called()
            pending.unlink()
            with patch.object(harness, 'PROBE_COST', 4.01):
                with self.assertRaisesRegex(RuntimeError, 'Budget'):
                    harness.call('test', {})

    def test_failure_keeps_pending_and_new_run_keeps_spending(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(run, 'STATE', Path(directory)):
            harness = run.historical_harness()
            initial = sum(r['conservative_cost'] for r in harness.records())
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-only'}), patch.object(
                    harness.urllib.request, 'urlopen', side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):
                    harness.call('uia:uncertain', {})
            self.assertTrue((Path(directory) / 'pending.json').exists())
            second = run.historical_harness()
            self.assertEqual(initial, sum(r['conservative_cost'] for r in second.records()))

    def test_phase_order_and_corpus_binding(self):
        dataset = {'source': 'recorded-windows-uia', 'choices': protocol.tasks('notepad', snapshot()),
                   'verification': []}
        with tempfile.TemporaryDirectory() as directory, patch.object(run, 'STATE', Path(directory)):
            harness = run.historical_harness()
            with self.assertRaisesRegex(ValueError, 'run dev first'):
                run.execute(dataset, 'heldout', harness)
            self.assertTrue((Path(directory) / 'corpus.json').exists())
            dataset['run_id'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'corpus changed'):
                run.execute(dataset, 'dev', harness)

    def test_split_family_integrity(self):
        rows = protocol.tasks('notepad', snapshot()) + protocol.tasks('winforms', snapshot())
        dataset = {'source': 'recorded-windows-uia', 'choices': rows}
        evaluate.check_dataset(dataset)
        changed = copy.deepcopy(dataset)
        changed['choices'][-1]['split'] = 'dev'
        with self.assertRaisesRegex(ValueError, 'application split'):
            evaluate.check_dataset(changed)
        self.assertEqual(protocol.SPLITS['open-dialog'], protocol.SPLITS['winforms'])
        self.assertEqual(protocol.SPLITS['save-dialog'], protocol.SPLITS['winforms'])
        changed = copy.deepcopy(dataset)
        changed['choices'][-1]['expected'] = 'corrupt-gold'
        with self.assertRaisesRegex(ValueError, 'task digest'):
            evaluate.check_dataset(changed)


if __name__ == '__main__':
    unittest.main()
