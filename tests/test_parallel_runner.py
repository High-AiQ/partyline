"""Unit tests for parallel discovery and worker accounting, without subprocesses."""

import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import call, patch

from scripts.parallel_test import (
    confirm_violations,
    first_pass_violations,
    make_shards,
    summarize_workers,
)


def worker_output(tests: int, skips: int = 0) -> str:
    suffix = f" (skipped={skips})" if skips else ""
    return f"\nRan {tests} tests in 0.001s\n\nOK{suffix}\n"


def completed(tests: int, skips: int = 0, returncode: int = 0):
    return subprocess.CompletedProcess(["fake-worker"], returncode, worker_output(tests, skips))


class WorkerAccountingTest(unittest.TestCase):
    def summarize(self, results):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return summarize_workers(results)

    def test_each_shard_and_their_sum_match_discovery(self):
        total, skipped, okay = self.summarize([
            (completed(2, skips=1), 2),
            (completed(3, skips=2), 3),
        ])

        self.assertTrue(okay)
        self.assertEqual((total, skipped), (5, 3))

    def test_compensating_shard_counts_cannot_hide_a_missing_test(self):
        total, skipped, okay = self.summarize([
            (completed(1), 2),
            (completed(4), 3),
        ])

        self.assertFalse(okay)
        self.assertEqual((total, skipped), (5, 0))

    def test_a_failed_worker_fails_even_with_its_expected_count(self):
        total, skipped, okay = self.summarize([(completed(1, returncode=1), 1)])

        self.assertFalse(okay)
        self.assertEqual((total, skipped), (1, 0))


class TimingGuardTest(unittest.TestCase):
    def test_only_unallowlisted_first_pass_outliers_are_rerun_once(self):
        rows = [
            {"id": "tests.example.fast", "seconds": 1.0},
            {"id": "tests.example.slow", "seconds": 1.2},
            {"id": "tests.example.slow", "seconds": 1.5},
            {"id": "tests.example.allowed", "seconds": 2.0},
        ]
        with patch("scripts.parallel_test.SLOW_TEST_ALLOWLIST", {"tests.example.allowed": "work"}):
            violations = first_pass_violations(rows)

        self.assertEqual(violations, {"tests.example.slow": 1.5})

    def test_an_isolated_rerun_clears_a_scheduler_outlier_and_prints_both(self):
        output = io.StringIO()
        with redirect_stdout(output):
            okay = confirm_violations(
                {"tests.example.slow": 1.4}, lambda ident, index: (0.2, True)
            )

        self.assertTrue(okay)
        self.assertIn("first=1.400s, rerun=0.200s", output.getvalue())

    def test_only_a_failed_missing_or_still_slow_rerun_fails(self):
        for result in ((0.2, False), (None, True), (1.2, True)):
            with self.subTest(result=result), redirect_stdout(io.StringIO()), redirect_stderr(
                io.StringIO()
            ):
                self.assertFalse(confirm_violations(
                    {"tests.example.slow": 1.4}, lambda ident, index, result=result: result
                ))


class ModuleShardTest(unittest.TestCase):
    def test_modules_are_counted_through_the_workers_loader(self):
        suites = {
            "tests.test_a": unittest.TestSuite(
                unittest.FunctionTestCase(lambda: None) for _ in range(2)
            ),
            "tests.test_b": unittest.TestSuite([unittest.FunctionTestCase(lambda: None)]),
        }
        paths = [Path("tests/test_b.py"), Path("tests/test_a.py")]
        with patch("scripts.parallel_test.Path.glob", return_value=paths), patch.object(
            unittest.defaultTestLoader, "loadTestsFromName", side_effect=suites.__getitem__
        ) as load:
            shards = make_shards(2)

        self.assertEqual(load.call_args_list, [call("tests.test_a"), call("tests.test_b")])
        self.assertEqual(shards, [(["tests.test_a"], 2), (["tests.test_b"], 1)])


if __name__ == "__main__":
    unittest.main()
