"""The one mapping from changed paths to a light task's gate commands."""

import unittest

from partyline.task_gates import FRONTEND, FULL, RUFF, TESTS, changed_paths, gates_for, main


class GatesTest(unittest.TestCase):
    def test_docs_markdown_and_skills_only_run_no_gates(self):
        self.assertEqual(gates_for(['docs/hierarchy.md', 'README.md', 'skills/x/SKILL.md',
                                    'docs/img.txt']), [])
        self.assertEqual(gates_for([]), [])

    def test_python_runs_ruff_and_the_tests_for_the_touched_module(self):
        gates = gates_for(['partyline/task_gates.py'])
        self.assertEqual(gates[0], RUFF)
        self.assertTrue(gates[1].startswith(TESTS))
        self.assertIn('tests.test_task_gates', gates[1])

    def test_a_test_file_runs_itself_and_a_module_finds_its_importers(self):
        self.assertEqual(gates_for(['tests/test_task_gates.py']),
                         [RUFF, f'{TESTS} tests.test_task_gates'])
        gates = gates_for(['partyline/orchestrator_pack.py'])
        self.assertIn('tests.test_orchestrator_express', gates[1])

    def test_frontend_and_its_bundle_run_verify_and_build(self):
        self.assertEqual(gates_for(['frontend/src/a.ts']), [FRONTEND])
        self.assertEqual(gates_for(['partyline/static/index.html']), [FRONTEND])

    def test_mixed_changes_are_the_union_without_repeats(self):
        gates = gates_for(['docs/a.md', 'frontend/src/a.ts', 'partyline/task_gates.py',
                           'tests/test_task_gates.py', 'frontend/src/b.svelte'])
        self.assertEqual((gates[0], gates[-1], len(gates)), (RUFF, FRONTEND, 3))
        self.assertIn('tests.test_task_gates', gates[1])

    def test_unknown_paths_and_untested_modules_fall_back_to_the_full_gates(self):
        self.assertEqual(gates_for(['pyproject.toml']), FULL)
        self.assertEqual(gates_for(['partyline/no_such_module_anywhere.py']), FULL)
        self.assertEqual(gates_for(['tests/helper_nobody_imports.py']), FULL)

    def test_the_version_bump_adds_lint_only_and_keeps_a_focused_fix_focused(self):
        bump = gates_for(['partyline/__init__.py'])
        self.assertEqual(bump, [RUFF])
        fix = gates_for(['partyline/task_gates.py', 'tests/test_task_gates.py',
                         'partyline/__init__.py', 'docs/hierarchy.md'])
        self.assertEqual(fix[0], RUFF)
        self.assertEqual(len(fix), 2)
        self.assertNotIn('./scripts/capped-test', fix)
        self.assertIn('tests.test_task_gates', fix[1])

    def test_a_shared_test_helper_runs_the_tests_that_import_it(self):
        gates = gates_for(['tests/orchestrator_fixture.py'])
        self.assertEqual(gates[0], RUFF)
        self.assertIn('tests.test_orchestrator_express', gates[1])
        self.assertIn('tests.test_orchestrator_reopen', gates[1])
        self.assertNotIn('tests.test_task_gates', gates[1])

    def test_cli_prints_gates_and_the_changed_paths_come_from_git(self):
        self.assertEqual(main(['docs/a.md']), 0)
        self.assertIsInstance(changed_paths(), list)
