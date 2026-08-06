"""Controls for the exact-generation cockpit restart executable."""

import signal
import tempfile
import unittest
from pathlib import Path

from scripts.restart_server import (
    EXIT_ALREADY_GONE,
    EXIT_WRONG_GENERATION,
    RestartRefused,
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

    def invoke(self, generation, wait=lambda *_: None):
        return run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            generation=generation,
            signal_process=lambda pid, sig: self.signals.append((pid, sig)),
            wait=wait,
            launch=lambda server, logfile, cwd: self.executions.append(
                (server, logfile, cwd)
            ),
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
        self.assertEqual(self.executions, [(self.server, self.log, self.root)])


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
