"""Controls for the exact-generation cockpit restart executable."""

import signal
import tempfile
import unittest
from pathlib import Path

from scripts.restart_server import (
    EXIT_ALREADY_GONE,
    EXIT_COMMAND_LINE_UNREADABLE,
    EXIT_ENVIRONMENT_UNREADABLE,
    EXIT_REPLACEMENT_UNIMPORTABLE,
    EXIT_WRONG_GENERATION,
    RestartRefused,
    process_cmdline,
    process_environment,
    process_generation,
    run_restart,
    wait_for_generation_exit,
)


class GenerationParserTest(unittest.TestCase):
    def test_field_22_is_parsed_without_shell_quoting(self):
        """The negative control for the failed inline ``awk '$22'`` unit."""
        with tempfile.TemporaryDirectory() as directory:
            stat = Path(directory) / "42" / "stat"
            stat.parent.mkdir()
            suffix = ["S", *map(str, range(4, 23))]
            stat.write_text(f"42 (party line worker) {' '.join(suffix)}\n")
            self.assertEqual(process_generation(42, Path(directory)), "22")

    def test_missing_or_malformed_stat_is_not_a_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(process_generation(42, root))
            stat = root / "42" / "stat"
            stat.parent.mkdir()
            stat.write_text("not a proc stat")
            self.assertIsNone(process_generation(42, root))


class EnvironmentParserTest(unittest.TestCase):
    def test_the_old_generations_environ_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            environ = Path(directory) / "42" / "environ"
            environ.parent.mkdir()
            environ.write_bytes(b"PATH=/home/g/.local/bin:/usr/bin\0EMPTY=\0\0junk\0")
            self.assertEqual(
                process_environment(42, Path(directory)),
                {"PATH": "/home/g/.local/bin:/usr/bin", "EMPTY": ""},
            )

    def test_a_missing_or_empty_environ_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(process_environment(42, root))
            environ = root / "42" / "environ"
            environ.parent.mkdir()
            environ.write_bytes(b"")
            self.assertIsNone(process_environment(42, root))

    def test_the_old_generations_cmdline_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            cmdline = Path(directory) / "42" / "cmdline"
            cmdline.parent.mkdir()
            cmdline.write_bytes(b"/usr/bin/python3\0/home/g/.venv/bin/partyline\0--port\09000\0")
            self.assertEqual(
                process_cmdline(42, Path(directory)),
                ["/usr/bin/python3", "/home/g/.venv/bin/partyline", "--port", "9000"],
            )

    def test_a_missing_or_empty_cmdline_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(process_cmdline(42, root))
            cmdline = root / "42" / "cmdline"
            cmdline.parent.mkdir()
            cmdline.write_bytes(b"")
            self.assertIsNone(process_cmdline(42, root))


class RestartTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.server = self.root / "partyline"
        self.server.write_text("#!/bin/sh\nexit 0\n")
        self.server.chmod(0o755)
        self.log = self.root / "cockpit.log"
        self.signals = []
        self.executions = []

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, generation, wait=lambda *_: None,
               environment=lambda _pid: {"PATH": "/old/server/path"}):
        return run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            generation=generation,
            environment=environment,
            command_line=lambda _pid: [str(self.server)],
            signal_process=lambda pid, sig: self.signals.append((pid, sig)),
            wait=wait,
            launch=lambda server, logfile, cwd, env, arguments: self.executions.append(
                (server, logfile, cwd, env, arguments)
            ),
            probe=lambda _cwd, _server: None,
        )

    def test_an_unreadable_generation_is_refused_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            self.invoke(lambda _pid: None)
        self.assertEqual(raised.exception.exit_code, EXIT_ALREADY_GONE)
        self.assertEqual(self.signals, [])

    def test_a_different_generation_is_refused_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            self.invoke(lambda _pid: "5678")
        self.assertEqual(raised.exception.exit_code, EXIT_WRONG_GENERATION)
        self.assertEqual(self.signals, [])

    def test_a_matching_generation_is_waited_and_execed(self):
        waited = []
        self.invoke(lambda _pid: "1234", lambda pid, start: waited.append((pid, start)))
        self.assertEqual(self.signals, [(42, signal.SIGTERM)])
        self.assertEqual(waited, [(42, "1234")])
        self.assertEqual(
            self.executions,
            [(self.server, self.log, self.root, {"PATH": "/old/server/path"}, [])],
        )

    def test_the_replacement_inherits_the_old_generations_environment(self):
        """The trigger runs under systemd's stripped PATH; the server must not."""
        self.invoke(lambda _pid: "1234")
        _server, _log, _cwd, env, _arguments = self.executions[0]
        self.assertEqual(env, {"PATH": "/old/server/path"})

    def test_the_replacement_inherits_flags_after_the_console_script(self):
        executions = []
        run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            generation=lambda _pid: "1234",
            environment=lambda _pid: {"PATH": "/old/server/path"},
            command_line=lambda _pid: [
                "/usr/bin/python3", str(self.server), "--host", "0.0.0.0", "--port", "9000"
            ],
            signal_process=lambda *_args: None,
            wait=lambda *_args: None,
            launch=lambda *args: executions.append(args),
            probe=lambda _cwd, _server: None,
        )
        self.assertEqual(executions[0][-1], ["--host", "0.0.0.0", "--port", "9000"])

    def test_an_unreadable_environ_refuses_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            self.invoke(lambda _pid: "1234", environment=lambda _pid: None)
        self.assertEqual(raised.exception.exit_code, EXIT_ENVIRONMENT_UNREADABLE)
        self.assertEqual(self.signals, [])
        self.assertEqual(self.executions, [])

    def test_an_unreadable_cmdline_refuses_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            run_restart(
                42,
                "1234",
                self.server,
                self.log,
                self.root,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PATH": "/old/server/path"},
                command_line=lambda _pid: None,
                signal_process=lambda pid, sig: self.signals.append((pid, sig)),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: None,
            )
        self.assertEqual(raised.exception.exit_code, EXIT_COMMAND_LINE_UNREADABLE)
        self.assertEqual(self.signals, [])
        self.assertEqual(self.executions, [])

    def test_an_unimportable_replacement_is_refused_before_signalling(self):
        """The failing control for the v0.32.0 Pillow outage.

        A tree that imports a dep the cockpit venv does not have must not
        SIGTERM the live generation. The control error is the one from
        cockpit.log: ModuleNotFoundError: No module named 'PIL'.
        """
        with self.assertRaises(RestartRefused) as raised:
            run_restart(
                42,
                "1234",
                self.server,
                self.log,
                self.root,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PATH": "/old/server/path"},
                command_line=lambda _pid: [str(self.server)],
                signal_process=lambda pid, sig: self.signals.append((pid, sig)),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: "ModuleNotFoundError: No module named 'PIL'",
            )
        self.assertEqual(raised.exception.exit_code, EXIT_REPLACEMENT_UNIMPORTABLE)
        self.assertIn("PIL", str(raised.exception))
        self.assertEqual(self.signals, [])
        self.assertEqual(self.executions, [])

    def test_a_bootable_replacement_is_still_signalled(self):
        run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            generation=lambda _pid: "1234",
            environment=lambda _pid: {"PATH": "/old/server/path"},
            command_line=lambda _pid: [str(self.server)],
            signal_process=lambda pid, sig: self.signals.append((pid, sig)),
            wait=lambda *_args: None,
            launch=lambda *args: self.executions.append(args),
            probe=lambda _cwd, _server: None,
        )
        self.assertEqual(self.signals, [(42, signal.SIGTERM)])
        self.assertEqual(len(self.executions), 1)


class WaitTest(unittest.TestCase):
    def test_a_reused_pid_counts_as_the_old_generation_exiting(self):
        generations = iter(["1234", "9999"])
        wait_for_generation_exit(
            42,
            "1234",
            generation=lambda _pid: next(generations),
            monotonic=lambda: 0,
            sleep=lambda _seconds: None,
        )

    def test_timeout_is_distinct_and_bounded(self):
        clock = iter([0.0, 0.0, 1.0])
        with self.assertRaises(RestartRefused) as raised:
            wait_for_generation_exit(
                42,
                "1234",
                generation=lambda _pid: "1234",
                monotonic=lambda: next(clock),
                sleep=lambda _seconds: None,
                timeout=0.5,
            )
        self.assertIn("did not exit", str(raised.exception))


class FailureReportingTest(unittest.TestCase):
    def test_a_pre_kill_refusal_is_posted_to_the_planned_line(self):
        import scripts.restart_server as restart

        original_run, original_post = restart.run_restart, restart.post_failure
        reports = []
        try:
            restart.run_restart = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RestartRefused("generation mismatch", EXIT_WRONG_GENERATION)
            )
            restart.post_failure = lambda url, message: reports.append((url, message))
            result = restart.main([
                "42", "1234", "/bin/true", "/tmp/log", "/tmp",
                "--failure-ws", "ws://127.0.0.1:8642/ws/line",
            ])
        finally:
            restart.run_restart, restart.post_failure = original_run, original_post
        self.assertEqual(result, EXIT_WRONG_GENERATION)
        self.assertEqual(reports[0][0], "ws://127.0.0.1:8642/ws/line")
        self.assertIn("generation mismatch", reports[0][1])
        self.assertIn("remains unclaimed", reports[0][1])


if __name__ == "__main__":
    unittest.main()
