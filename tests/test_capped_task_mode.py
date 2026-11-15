"""Unscoped capped-test is allowed only outside task pairs or in suite mode."""

import io
import json
import os
import runpy
import unittest
from contextlib import redirect_stderr
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from partyline.adapters.briefing import child_env


class CappedTaskModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = runpy.run_path('scripts/capped-test')
        cls.namespace = cls.script['main'].__globals__

    def test_launch_mode_overrides_inherited_mode(self):
        env = child_env({'PARTYLINE_TASK_MODE': 'suite'}, {'task_mode': 'full'})
        self.assertEqual(env['PARTYLINE_TASK_MODE'], 'full')
        self.assertEqual(child_env(env, {})['PARTYLINE_TASK_MODE'], '')
        self.assertEqual(child_env({}, {'task_mode': 'suite'})['PARTYLINE_TASK_MODE'], 'suite')

    def run_main(self, mode, arguments):
        env = {} if mode is None else {'PARTYLINE_TASK_MODE': mode}
        with patch.dict(os.environ, env, clear=True), patch.dict(
                self.namespace, {'run_capped': lambda *_: 0}) as namespace, redirect_stderr(io.StringIO()):
            return namespace['main'](arguments)

    def test_default_suite_is_refused_before_any_cap_or_test_command_runs(self):
        for mode in ['full', 'express', 'light']:
            with self.subTest(mode=mode), patch.dict(os.environ, {'PARTYLINE_TASK_MODE': mode}, clear=True):
                error = io.StringIO()
                with redirect_stderr(error), patch.dict(self.namespace, {
                        'run_capped': lambda *_: self.fail('must not launch'),
                        'systemd_available': lambda *_: self.fail('must not probe')}):
                    self.assertEqual(self.script['main'](['--workers', '2']), 125)
                self.assertIn('scoped gates: python -m partyline.task_gates', error.getvalue())

    def test_suite_lines_and_outside_partyline_can_run_default_suite(self):
        for mode in [None, '', 'suite']:
            self.assertEqual(self.run_main(mode, []), 0)

    def test_explicit_test_commands_are_allowed_and_environment_is_isolated(self):
        def run(command, limit, env):
            self.assertIn('tests.test_task_gates', command)
            self.assertNotIn('PARTYLINE_TASK_MODE', env)
            self.assertNotIn('PARTYLINE_CONV_ID', env)
            self.assertTrue(env['PARTYLINE_DB'].endswith('partyline.db'))
            return 0
        with patch.dict(os.environ, {'PARTYLINE_TASK_MODE': 'full'}, clear=True), patch.dict(
                self.namespace, {'run_capped': run}):
            self.assertEqual(self.script['main'](['python', '-m', 'unittest', 'tests.test_task_gates']), 0)

    def test_older_attachments_query_mode_once_and_fail_closed_when_unavailable(self):
        env = {'PARTYLINE_API': 'https://example.test', 'PARTYLINE_CONV_ID': 'task',
               'PARTYLINE_TOKEN': 'test'}
        for mode, refused in [('full', True), ('express', True), ('suite', False)]:
            with patch.dict(os.environ, env, clear=True), patch('urllib.request.urlopen') as fetch:
                fetch.return_value.__enter__.return_value = io.StringIO(json.dumps({'mode': mode}))
                self.assertEqual(self.script['task_suite_refusal']() is not None, refused)
                fetch.assert_called_once()
        for failure, refused in [(URLError('offline'), True),
                                 (HTTPError('https://example.test', 404, 'ordinary line', {}, None), False),
                                 (HTTPError('https://example.test', 403, 'denied', {}, None), True)]:
            with patch.dict(os.environ, env, clear=True), patch(
                    'urllib.request.urlopen', side_effect=failure):
                self.assertEqual(self.script['task_suite_refusal']() is not None, refused)
        with patch.dict(os.environ, {'PARTYLINE_CONV_ID': 'task'}, clear=True):
            self.assertIsNotNone(self.script['task_suite_refusal']())

    def test_mcp_legacy_call_is_normalized_without_advertising_a_light_choice(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from partyline.mcp.tools_tasks import call, tool_list
        client = SimpleNamespace(home='root', request=Mock(return_value={}))
        state = {'actions': ['create_task']}
        schema = tool_list(state)[0]['inputSchema']
        self.assertEqual(schema['properties']['mode']['enum'], ['full', 'express', 'suite'])
        call(client, 'create_task', {'name': 'task', 'goal': 'change', 'implementer': 'builder',
                                    'mode': 'light'}, state)
        self.assertEqual(client.request.call_args.args[2]['mode'], 'full')

    def test_unscoped_unittest_commands_refuse_before_any_tests_can_launch(self):
        commands = [
            ['uv', 'run', '--locked', 'python', '-m', 'unittest'],
            ['python', '-m', 'unittest', '-v'],
            ['python', '-m', 'unittest', '-k', 'selected'],
            ['python', '-m', 'unittest', 'discover'],
            ['python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test*.py'],
            ['python', '-m', 'unittest', 'tests'],
            ['python', '-m', 'scripts.parallel_test', '--workers', '2'],
            ['python', 'scripts/parallel_test.py'],
            ['coverage', 'run', '-m', 'unittest'],
        ]
        for mode in ['full', 'express', 'light']:
            for command in commands:
                with self.subTest(mode=mode, command=command), patch.dict(
                        os.environ, {'PARTYLINE_TASK_MODE': mode}, clear=True), patch.dict(
                        self.namespace, {'run_capped': lambda *_: self.fail('must not launch')}):
                    error = io.StringIO()
                    with redirect_stderr(error):
                        self.assertEqual(self.script['main'](command), 125)
                    self.assertIn('scoped gates', error.getvalue())
        for mode in [None, '', 'suite']:
            for command in commands:
                self.assertEqual(self.run_main(mode, command), 0)

    def test_named_unittest_modules_are_still_allowed_with_options_and_wrappers(self):
        commands = [
            ['uv', 'run', '--locked', 'python', '-m', 'unittest', 'tests.test_task_gates'],
            ['python', '-m', 'unittest', '-v', '-k', 'selected', 'tests.test_task_gates'],
            ['python', '-m', 'unittest', 'tests/test_task_gates.py'],
            ['python', '-m', 'unittest', '-k', 'discover', 'tests.test_task_gates'],
        ]
        for mode in ['full', 'express']:
            for command in commands:
                with self.subTest(mode=mode, command=command):
                    self.assertEqual(self.run_main(mode, command), 0)
