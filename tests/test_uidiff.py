"""Unit coverage for the visual parity comparison.

The comparison is the part with a wrong answer available to it — a refactor
that moved something and was reported clean. It is pure functions over
{name: digest} maps, so none of this needs a browser.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bundle_identity import (  # noqa: E402
    StaleBundle,
    committed_build_id,
    source_build_id,
    stale_bundle_error,
)
from scripts.uidiff import (  # noqa: E402
    Change,
    HarnessBusy,
    capture,
    exclusive_run,
    Difference,
    compare,
    digest,
    digests,
    judgeable,
    merge_confirm_only,
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
        current = reconcile({"a": "old"}, {"a": "blip"})
        self.assertEqual(current.unstable, ("a",))
        self.assertNotIn("a", current.stable)

    def test_unstable_names_are_sorted_so_the_report_is_stable(self):
        result = reconcile({"c": "1", "a": "1"}, {"c": "2", "a": "2"})
        self.assertEqual(result.unstable, ("a", "c"))


class JudgeableTest(unittest.TestCase):
    """A wobbly state must not be reported as a deleted one.

    This is a reporting bug with teeth: the first run of the parity check on the
    TypeScript conversion said `07-delete-confirm is gone`, and the honest
    answer was that its capture had raced a fetch. The wrong wording is worse
    than no wording, because it names a failure mode that is not happening.
    """

    BASE = {"a": "1", "b": "2", "c": "3"}

    def test_an_unstable_state_is_withheld_from_judgement(self):
        self.assertEqual(judgeable(self.BASE, ("b",)), {"a": "1", "c": "3"})

    def test_nothing_unstable_means_everything_is_judged(self):
        self.assertEqual(judgeable(self.BASE, ()), self.BASE)

    def test_an_unstable_state_is_never_reported_as_removed(self):
        unstable = ("b",)
        judged = judgeable(self.BASE, unstable)
        # `b` is missing from this run's stable set precisely because it wobbled.
        comparable = {"a": "1", "c": "3"}
        self.assertEqual(compare(judged, comparable), [])

    def test_a_genuinely_removed_state_is_still_reported(self):
        # The guard must not swallow the real case it resembles.
        judged = judgeable(self.BASE, ())
        self.assertEqual(compare(judged, {"a": "1", "b": "2"}), [Difference("c", Change.REMOVED)])


def check_differences(known, trusted, unstable, current):
    """The comparison wiring `check()` performs, mirrored for the tests.

    `known` is every state the baseline recorded; `trusted` is the subset it
    could pin down (stable-states.txt). The mirror is deliberate — this is the
    composition the real command runs, and the invariants below are its contract.
    """
    baseline = {name: value for name, value in known.items() if name in trusted}
    judged = judgeable(baseline, unstable)
    comparables = {name: value for name, value in current.items()
                   if name in judged or name not in known}
    return compare(judged, comparables)


class CheckCompositionTest(unittest.TestCase):
    """The three-way distinction `check()` must keep straight: trusted states
    are judged, recorded-but-untrusted states are neither judged nor reported,
    and states the baseline never recorded are reported as new."""

    def test_a_state_the_baseline_never_recorded_is_reported_as_new(self):
        # `check()` used to filter the current capture to baseline names before
        # comparing, which made the ADDED path unreachable — so a harness that
        # gained a state silently lost coverage against an older baseline.
        known = {"a": "1"}
        self.assertEqual(check_differences(known, {"a"}, (), {"a": "1", "18-gate": "new"}),
                         [Difference("18-gate", Change.ADDED)])

    def test_a_known_but_untrusted_state_is_not_reported_as_new(self):
        # The baseline recorded `13-mention-popover` but never pinned it down,
        # so it is absent from stable-states.txt. A run that finally stabilises
        # it must not be misreported as a new state — it is known, just untrusted.
        known = {"a": "1", "wobbly": "2"}
        self.assertEqual(check_differences(known, {"a"}, (), {"a": "1", "wobbly": "2"}), [])

    def test_new_and_known_but_untrusted_states_are_told_apart(self):
        known = {"a": "1", "wobbly": "2"}
        current = {"a": "1", "wobbly": "2", "18-gate": "new"}
        self.assertEqual(check_differences(known, {"a"}, (), current),
                         [Difference("18-gate", Change.ADDED)])

    def test_a_wobbly_current_state_stays_out_of_the_judgement(self):
        # reconcile() quarantines a wobbly state into `unstable`; it never
        # reaches the stable set, so it is neither judged nor reported as new.
        known = {"a": "1"}
        self.assertEqual(check_differences(known, {"a"}, ("wobbly-now",), {"a": "1"}), [])


class ExclusiveRunTest(unittest.TestCase):
    """Two captures must never overlap.

    Both commands write fixed directories under the repository, and when two
    runs shared them they deleted each other's images mid-flight — after which
    the *missing* screenshots were reported as visual differences. That is the
    worst failure a parity harness can have: invented regressions look exactly
    like real ones, and everything it says stops being trustworthy.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.lock = Path(self.directory.name) / "uidiff.lock"

    def tearDown(self):
        self.directory.cleanup()

    def test_a_second_run_is_refused_while_the_first_holds_the_lock(self):
        with exclusive_run(self.lock):
            with self.assertRaises(HarnessBusy):
                with exclusive_run(self.lock):
                    self.fail("two captures ran at once")

    def test_the_refusal_says_what_to_do_about_it(self):
        with exclusive_run(self.lock):
            with self.assertRaises(HarnessBusy) as refused:
                with exclusive_run(self.lock):
                    pass
        self.assertIn("must not overlap", str(refused.exception))

    def test_the_lock_is_released_when_the_run_finishes(self):
        with exclusive_run(self.lock):
            pass
        with exclusive_run(self.lock):  # would raise if the first never let go
            pass

    def test_the_lock_is_released_even_when_the_run_fails(self):
        # A crashed capture must not wedge the harness for everyone after it.
        with self.assertRaises(ZeroDivisionError):
            with exclusive_run(self.lock):
                raise ZeroDivisionError
        with exclusive_run(self.lock):
            pass

    def test_a_separate_process_is_refused_too(self):
        """The control that matters: `flock` is per open file description, so a
        same-process check could pass while real concurrent *processes* — which
        is how this actually happened — still trampled each other."""
        with exclusive_run(self.lock):
            probe = subprocess.run(
                [
                    sys.executable, "-c",
                    "import fcntl,sys;"
                    "h=open(sys.argv[1],'w');"
                    "\ntry:\n fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB);print('acquired')"
                    "\nexcept OSError:\n print('refused')",
                    str(self.lock),
                ],
                capture_output=True, text=True,
            )
        self.assertEqual(probe.stdout.strip(), "refused", probe.stderr)


class DescribeTest(unittest.TestCase):
    def test_each_kind_says_what_to_think(self):
        self.assertIn("different", Difference("x", Change.CHANGED).describe())
        self.assertIn("new", Difference("x", Change.ADDED).describe())
        self.assertIn("gone", Difference("x", Change.REMOVED).describe())

    def test_the_state_is_named_so_the_report_is_actionable(self):
        for change in Change:
            self.assertIn("07-delete-confirm", Difference("07-delete-confirm", change).describe())


def make_frontend(root: Path) -> Path:
    """A minimal frontend tree shaped the way `sourceBuildId()` expects it."""
    frontend = root / "frontend"
    (frontend / "src" / "lib").mkdir(parents=True)
    (frontend / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (frontend / "package.json").write_text('{"name": "partyline-frontend"}', encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    (frontend / "vite.config.js").write_text("// config", encoding="utf-8")
    (frontend / "src" / "App.svelte").write_text("<h1>hi</h1>", encoding="utf-8")
    (frontend / "src" / "lib" / "api.ts").write_text("export const api = 1;", encoding="utf-8")
    return frontend


class MergeConfirmOnlyTest(unittest.TestCase):
    """The confirm run's extra states join the persisted baseline, and a
    state present in both runs keeps the first run's capture.

    This is the production path: `capture_twice` publishes `first_dir` to the
    baseline and then calls `merge_confirm_only`, so a state only the second
    run produced is still *known* to the baseline — never later misreported as
    a genuinely new harness state.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        for name in ("first", "confirm"):
            (self.root / name).mkdir()

    def tearDown(self):
        self.directory.cleanup()

    def test_a_confirm_only_state_is_persisted(self):
        (self.root / "first" / "01-a.png").write_bytes(b"first-a")
        (self.root / "confirm" / "01-a.png").write_bytes(b"confirm-a")
        (self.root / "confirm" / "02-confirm-only.png").write_bytes(b"confirm-only")
        # capture_twice publishes first_dir to keep_dir, then merges the extras.
        shutil.copytree(self.root / "first", self.root / "keep")
        merge_confirm_only(self.root / "keep", self.root / "first", self.root / "confirm")
        self.assertEqual((self.root / "keep" / "01-a.png").read_bytes(), b"first-a")
        self.assertEqual((self.root / "keep" / "02-confirm-only.png").read_bytes(), b"confirm-only")
        self.assertEqual(sorted(p.name for p in (self.root / "keep").glob("*.png")),
                         ["01-a.png", "02-confirm-only.png"])

    def test_a_same_name_first_capture_is_not_overwritten(self):
        # The control that fails on the old implementation: subtracting full
        # Path objects across two different parents can never match, so every
        # confirm PNG overwrote the first run's. Comparing by filename keeps
        # the publication invariant that the first run's capture wins.
        (self.root / "first" / "01-a.png").write_bytes(b"first-a")
        (self.root / "confirm" / "01-a.png").write_bytes(b"confirm-a")
        shutil.copytree(self.root / "first", self.root / "keep")
        merge_confirm_only(self.root / "keep", self.root / "first", self.root / "confirm")
        self.assertEqual((self.root / "keep" / "01-a.png").read_bytes(), b"first-a")


class StaleBundleTest(unittest.TestCase):
    """The capture renders `partyline/static`, so it must refuse to run when
    that bundle was not built from the current source — otherwise a clean
    report is the old UI against itself, which is exactly how a refactor
    claimed pixel parity while breaking the narrow layout."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.frontend = make_frontend(self.root)
        self.static = self.root / "partyline" / "static"
        self.static.mkdir(parents=True)
        self.out = self.root / "shots"

    def tearDown(self):
        self.directory.cleanup()

    def write_build(self, build_id: str):
        (self.static / "build.json").write_text(json.dumps({"build": build_id}), encoding="utf-8")

    def test_the_source_id_matches_what_a_built_bundle_would_claim(self):
        self.write_build(source_build_id(self.frontend))
        self.assertIsNone(stale_bundle_error(self.frontend, self.static))

    def test_any_source_change_makes_the_bundle_stale(self):
        self.write_build(source_build_id(self.frontend))
        (self.frontend / "src" / "App.svelte").write_text("<h1>changed</h1>", encoding="utf-8")
        self.assertIsNotNone(stale_bundle_error(self.frontend, self.static))

    def test_test_files_and_type_declarations_do_not_invalidate_the_bundle(self):
        before = source_build_id(self.frontend)
        (self.frontend / "src" / "lib" / "api.test.ts").write_text("// new test", encoding="utf-8")
        (self.frontend / "src" / "types.d.ts").write_text("type T = string;", encoding="utf-8")
        self.assertEqual(source_build_id(self.frontend), before)

    def test_the_source_id_is_deterministic(self):
        self.assertEqual(source_build_id(self.frontend), source_build_id(self.frontend))

    def test_a_missing_build_json_refuses_with_the_fix(self):
        error = stale_bundle_error(self.frontend, self.static)
        self.assertIsNotNone(error)
        self.assertIn("npm run build", error)

    def test_a_stale_bundle_refuses_with_the_fix(self):
        self.write_build("0123456789abcdef")
        error = stale_bundle_error(self.frontend, self.static)
        self.assertIsNotNone(error)
        self.assertIn("npm run build", error)

    def test_garbage_build_json_is_treated_as_missing(self):
        (self.static / "build.json").write_text("not json", encoding="utf-8")
        self.assertIsNone(committed_build_id(self.static))

    def test_capture_refuses_a_stale_bundle_before_opening_a_browser(self):
        self.write_build("0000000000000000")
        with self.assertRaises(StaleBundle):
            capture(self.out, frontend_dir=self.frontend, static_dir=self.static)


if __name__ == "__main__":
    unittest.main()
