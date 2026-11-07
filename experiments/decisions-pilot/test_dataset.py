"""Dataset integrity checks; no network and no waits."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generate


class DatasetIntegrityTest(unittest.TestCase):
    def test_split_templates_layouts_tasks_and_target_positions(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(generate, 'OUT', Path(directory)):
            generate.main()
            dataset = json.loads((Path(directory) / 'dataset.json').read_text())
            for kind, count in [('choices', 100), ('verification', 30)]:
                data = dataset[kind]
                dev = [r for r in data if r['split'] == 'dev']
                held = [r for r in data if r['split'] == 'heldout']
                self.assertEqual((len(dev), len(held)), (count, count))
                self.assertTrue({r['template'] for r in dev}.isdisjoint(r['template'] for r in held))
                self.assertTrue({r['layout'] for r in dev}.isdisjoint(r['layout'] for r in held))
                # Compare actual geometry, not just declared template IDs or names.
                def geometry(row, field='candidates' if kind == 'choices' else 'before'):
                    controls = row[field]
                    return tuple(tuple(c['bounds']) for c in controls)

                self.assertTrue({geometry(r) for r in dev}.isdisjoint(geometry(r) for r in held))
                if kind == 'choices':
                    def candidate_names(row):
                        return tuple(sorted(c['name'] for c in row['candidates']))

                    self.assertTrue({candidate_names(r) for r in dev}.isdisjoint(
                        candidate_names(r) for r in held))
                if kind == 'verification':
                    self.assertTrue({r['expected_field'] for r in dev}.isdisjoint(
                        r['expected_field'] for r in held))
            for split in ('dev', 'heldout'):
                choices = [r for r in dataset['choices'] if r['split'] == split]
                targets = {r['expected'] for r in choices if r['expected'] != 'abstain'}
                self.assertEqual(targets, {'e0', 'e1', 'e2'})
                self.assertEqual({r['case'] for r in choices},
                                 {'normal', 'absent', 'duplicate', 'stale', 'popup', 'adversarial'})
                self.assertEqual({r['label'] for r in dataset['verification'] if r['split'] == split},
                                 {'success', 'failed', 'unknown'})


if __name__ == '__main__':
    unittest.main()
