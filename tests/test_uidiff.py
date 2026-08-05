"""Unit coverage for the visual parity comparison.

The comparison is the part with a wrong answer available to it — a refactor
that moved something and was reported clean. It is pure functions over
{name: digest} maps, so none of this needs a browser.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.uidiff import (  # noqa: E402
    Change,
    Difference,
    compare,
    digest,
    digests,
    reconcile,
    same_shots,
)


class DigestTest(unittest.TestCase):
    def test_identical_bytes_have_the_same_digest(self):
        self.assertEqual(digest(b"png-bytes"), digest(b"png-bytes"))

    def test_one_changed_byte_changes_the_digest(self):
        self.assertNotEqual(digest(b"png-bytes"), digest(b"png-byteS"))

    def test_a_missing_directory_is_no_shots_rather_than_a_crash(self):
        self.assertEqual(digests(Path("/nonexistent/never/created")), {})


class CompareTest(unittest.TestCase):
    BASE = {"01-sidebar": "aaa", "02-menu": "bbb"}

    def test_an_unchanged_run_reports_nothing(self):
        self.assertEqual(compare(self.BASE, dict(self.BASE)), [])
        self.assertTrue(same_shots(self.BASE, dict(self.BASE)))

    def test_a_changed_state_is_reported(self):
        differences = compare(self.BASE, {"01-sidebar": "aaa", "02-menu": "CHANGED"})
        self.assertEqual(differences, [Difference("02-menu", Change.CHANGED)])
        self.assertFalse(same_shots(self.BASE, {"01-sidebar": "aaa", "02-menu": "CHANGED"}))

    def test_a_state_that_vanished_is_reported_rather_than_skipped(self):
        # A capture that quietly stopped producing a shot would otherwise read
        # as a clean run, which is the exact failure this guards against.
        differences = compare(self.BASE, {"01-sidebar": "aaa"})
        self.assertEqual(differences, [Difference("02-menu", Change.REMOVED)])

    def test_a_new_state_is_reported_as_having_no_baseline(self):
        differences = compare(self.BASE, {**self.BASE, "03-new": "ccc"})
        self.assertEqual(differences, [Difference("03-new", Change.ADDED)])

    def test_every_kind_of_difference_is_reported_together(self):
        differences = compare(self.BASE, {"01-sidebar": "CHANGED", "03-new": "ccc"})
        self.assertEqual(
            differences,
            [
                Difference("01-sidebar", Change.CHANGED),
                Difference("03-new", Change.ADDED),
                Difference("02-menu", Change.REMOVED),
            ],
        )

    def test_changed_states_are_reported_in_a_stable_order(self):
        base = {"c": "1", "a": "1", "b": "1"}
        current = {"c": "2", "a": "2", "b": "2"}
        self.assertEqual([d.name for d in compare(base, current)], ["a", "b", "c"])

    def test_an_empty_baseline_makes_everything_new(self):
        self.assertEqual(
            compare({}, self.BASE),
            [Difference("01-sidebar", Change.ADDED), Difference("02-menu", Change.ADDED)],
        )


class ReconcileTest(unittest.TestCase):
    """Two captures of the same build, reconciled into what can be trusted.

    This is the part that makes the harness usable: headless Chromium is nearly
    but not quite deterministic, and a checker that reports a phantom change
    one run in three is one nobody reads.
    """

    def test_two_agreeing_runs_are_all_stable(self):
        result = reconcile({"a": "1", "b": "2"}, {"a": "1", "b": "2"})
        self.assertEqual(result.stable, {"a": "1", "b": "2"})
        self.assertEqual(result.unstable, ())

    def test_a_state_that_disagrees_with_itself_is_quarantined(self):
        result = reconcile({"a": "1", "b": "2"}, {"a": "1", "b": "FLAKE"})
        self.assertEqual(result.stable, {"a": "1"})
        self.assertEqual(result.unstable, ("b",))

    def test_a_state_only_one_run_produced_is_not_stable(self):
        result = reconcile({"a": "1"}, {"a": "1", "b": "2"})
        self.assertEqual(result.stable, {"a": "1"})
        self.assertEqual(result.unstable, ("b",))

    def test_a_real_change_still_reaches_the_comparison(self):
        # The whole design rests on this: a genuine change moves a state in
        # both runs, so it stays stable and is compared rather than excused.
        baseline = reconcile({"a": "old"}, {"a": "old"})
        current = reconcile({"a": "new"}, {"a": "new"})
        self.assertEqual(current.unstable, ())
        self.assertEqual(compare(baseline.stable, current.stable), [Difference("a", Change.CHANGED)])

    def test_a_flake_does_not_reach_the_comparison(self):
        baseline = reconcile({"a": "old"}, {"a": "old"})
        current = reconcile({"a": "old"}, {"a": "blip"})
        self.assertEqual(current.unstable, ("a",))
        self.assertNotIn("a", current.stable)

    def test_unstable_names_are_sorted_so_the_report_is_stable(self):
        result = reconcile({"c": "1", "a": "1"}, {"c": "2", "a": "2"})
        self.assertEqual(result.unstable, ("a", "c"))


class DescribeTest(unittest.TestCase):
    def test_each_kind_says_what_to_think(self):
        self.assertIn("different", Difference("x", Change.CHANGED).describe())
        self.assertIn("new", Difference("x", Change.ADDED).describe())
        self.assertIn("gone", Difference("x", Change.REMOVED).describe())

    def test_the_state_is_named_so_the_report_is_actionable(self):
        for change in Change:
            self.assertIn("07-delete-confirm", Difference("07-delete-confirm", change).describe())


if __name__ == "__main__":
    unittest.main()
