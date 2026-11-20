"""Task gates select direct tests and never fall back to full suites."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.task_gates import NO_DIRECT, RUFF, TESTS, changed_paths, frontend_gates, gates_for, main


class GatesTest(unittest.TestCase):
    def test_docs_and_empty_diff_need_no_gates(self):
        self.assertEqual(gates_for(['docs/hierarchy.md', 'README.md', 'skills/x/SKILL.md']), [])
        self.assertEqual(gates_for([]), [])

    def test_python_and_test_changes_are_deduplicated(self):
        gates = gates_for(['partyline/task_gates.py', 'tests/test_task_gates.py'])
        self.assertEqual(gates[0], RUFF)
        self.assertTrue(gates[1].startswith(TESTS))
        self.assertEqual(gates[1].count('tests.test_task_gates'), 1)
        self.assertFalse(any('coverage' in gate for gate in gates))
        self.assertEqual(gates_for(['partyline/__init__.py']), [RUFF])

    def test_unmapped_paths_and_modules_get_lint_and_an_explicit_suite_deferral(self):
        for path in ['unknown.bin', 'partyline/nobody_imports_me.py', 'tests/unknown_helper.py']:
            with self.subTest(path=path):
                with tempfile.TemporaryDirectory() as root:
                    self.assertEqual(gates_for([path], root), [RUFF, NO_DIRECT])

    def test_direct_tests_for_helpers_packaging_and_chrome(self):
        helper = gates_for(['partyline_helper/windows.py'])
        self.assertIn('tests.test_helper_windows', ' '.join(helper))
        self.assertIn('tests.test_windows_packaging', ' '.join(gates_for(['packaging/windows/entry.py'])))
        chrome = gates_for(['partyline_chrome/wire.js'])
        self.assertIn('node --test partyline_chrome/wire.test.js', chrome)
        self.assertNotIn('./scripts/capped-test', chrome)
        self.assertIn('partyline_chrome/wire.test.js', ' '.join(gates_for(['partyline_chrome/wire.test.js'])))

    def test_frontend_never_runs_whole_vitest_or_verify(self):
        paths = ['frontend/src/a.ts', 'frontend/src/b.svelte']
        with tempfile.TemporaryDirectory() as root:
            for path in paths:
                file = Path(root, path)
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            gates = gates_for(paths, root)
            self.assertEqual(gates, frontend_gates(paths, root))
        self.assertIn('npx prettier --check --ignore-unknown src/a.ts src/b.svelte', gates[0])
        self.assertIn('npx eslint --no-warn-ignored src/a.ts src/b.svelte', gates[1])
        self.assertIn('vitest related src/a.ts src/b.svelte --run', gates[3])
        self.assertEqual(gates[2], 'cd frontend && npm run check')
        self.assertEqual(gates[-1], 'cd frontend && npm run build')
        self.assertFalse(any('npm run verify' in gate or 'coverage' in gate for gate in gates))
        self.assertEqual(gates_for(['partyline/static/index.html']), [gates[2], gates[-1]])

    def test_deleted_frontend_paths_only_reach_related_tests_not_file_checkers(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'frontend/src').mkdir(parents=True)
            Path(root, 'frontend/src/present.ts').touch()
            gates = gates_for(['frontend/src/deleted.ts', 'frontend/src/present.ts'], root)
            for checker in gates[:2]:
                self.assertIn('src/present.ts', checker)
                self.assertNotIn('deleted.ts', checker)
            self.assertIn('vitest related src/deleted.ts src/present.ts --run', gates[3])
            deleted_only = frontend_gates(['frontend/src/deleted.ts'], root)
            self.assertFalse(any('prettier' in gate or 'eslint' in gate for gate in deleted_only))
            self.assertIn('vitest related src/deleted.ts --run', deleted_only[1])

    def test_browser_tests_are_deferred_and_paths_are_shell_quoted(self):
        self.assertEqual(gates_for(['tests/ui/test_layout.py']), [RUFF, NO_DIRECT])
        self.assertIn("'src/a;echo.ts'", ' '.join(gates_for(['frontend/src/a;echo.ts'])))

    def test_shared_test_helpers_select_importers(self):
        gates = gates_for(['tests/orchestrator_fixture.py'])
        self.assertIn('tests.test_orchestrator_express', gates[1])
        self.assertIn('tests.test_orchestrator_reopen', gates[1])

    def test_captain_tool_and_fixture_changes_select_role_contract_gates(self):
        for path in ("partyline/mcp/tools_captain.py", "partyline/mcp/captain_ops.py",
                     "tests/fixtures/mcp_role_matrix.json"):
            with self.subTest(path=path):
                self.assertIn("tests.test_mcp_role_matrix", " ".join(gates_for([path])))
        for path in ("partyline/mcp/tools_captain.py", "tests/fixtures/mcp_role_matrix.json"):
            with self.subTest(path=path):
                self.assertIn("tests.test_tool_names_in_texts", " ".join(gates_for([path])))

    def test_chrome_tests_importing_changed_files_are_included(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'partyline_chrome').mkdir()
            (root / 'partyline_chrome/flow.test.js').write_text("import './shared.js';")
            self.assertEqual(gates_for(['partyline_chrome/shared.js'], root),
                             [RUFF, 'node --test partyline_chrome/flow.test.js'])

    def test_cli_and_git_diff(self):
        with patch('builtins.print') as output, patch('partyline.task_gates._tests_for', return_value=[]):
            self.assertEqual(main(['unknown.bin']), 0)
        self.assertIn('no direct tests; covered by the suite run', output.call_args.args[0])
        self.assertIsInstance(changed_paths(), list)
