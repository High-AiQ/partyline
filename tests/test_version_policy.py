"""Controls for the pull-request release-version policy."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.version_policy import (
    Change,
    Version,
    history_verdict,
    required_bump,
    source_version,
    verdict,
)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "version_policy.py"


class VersionTest(unittest.TestCase):
    def test_parse_and_render(self):
        self.assertEqual(str(Version.parse("0.21.7")), "0.21.7")

    def test_rejects_non_release_versions(self):
        with self.assertRaisesRegex(ValueError, "plain SemVer"):
            Version.parse("0.21.8.dev1")

    def test_each_bump_resets_lower_components(self):
        version = Version(2, 3, 4)
        self.assertEqual(version.bumped("patch"), Version(2, 3, 5))
        self.assertEqual(version.bumped("minor"), Version(2, 4, 0))
        self.assertEqual(version.bumped("major"), Version(3, 0, 0))


class RequiredBumpTest(unittest.TestCase):
    def test_non_product_commits_require_no_release(self):
        subjects = ["docs: improve quick start", "test(wire): reject stale frames"]
        self.assertIsNone(required_bump(subjects))

    def test_highest_impact_wins_once_for_the_pr(self):
        subjects = ["fix(db): close race", "feat(ui): show live status", "fix: follow up"]
        self.assertEqual(required_bump(subjects), "minor")

    def test_breaking_marker_requires_major(self):
        self.assertEqual(required_bump(["feat(api)!: replace wire envelope"]), "major")

    def test_breaking_beats_feature_and_fix(self):
        subjects = ["fix(db): close race", "feat(ui): add search", "fix(api)!: remove v1"]
        self.assertEqual(required_bump(subjects), "major")

    def test_invalid_subject_is_rejected_even_if_another_commit_is_valid(self):
        with self.assertRaisesRegex(ValueError, "non-conventional"):
            required_bump(["fix: valid", "misc changes"])


class SourceVersionTest(unittest.TestCase):
    def test_reads_literal_without_importing_the_module(self):
        source = 'raise RuntimeError("must not execute")\n__version__ = "1.2.3"\n'
        self.assertEqual(source_version(source), Version(1, 2, 3))

    def test_refuses_a_computed_version(self):
        with self.assertRaisesRegex(ValueError, "literal __version__"):
            source_version('__version__ = ".".join(["1", "2", "3"])')


class VerdictTest(unittest.TestCase):
    BASE = Version(0, 21, 7)

    def test_patch_fix_passes(self):
        self.assertIsNone(verdict(self.BASE, Version(0, 21, 8), ["fix(db): close race"]))

    def test_feature_requires_exactly_one_minor_bump(self):
        failure = verdict(self.BASE, Version(0, 21, 8), ["feat(ui): add search"])
        self.assertIn("expected 0.22.0", failure)

    def test_missing_fix_bump_fails(self):
        failure = verdict(self.BASE, self.BASE, ["fix(proof): reject false receipt"])
        self.assertIn("patch bump required", failure)

    def test_multiple_fix_commits_still_require_one_patch_bump(self):
        subjects = ["fix(db): close race", "fix(db): handle cancellation"]
        self.assertIsNone(verdict(self.BASE, Version(0, 21, 8), subjects))

    def test_docs_only_version_bump_fails(self):
        failure = verdict(self.BASE, Version(0, 21, 8), ["docs: improve README"])
        self.assertIn("only docs/test/refactor/chore", failure)

    def test_refactor_does_not_create_a_release(self):
        self.assertIsNone(verdict(self.BASE, self.BASE, ["refactor(db): isolate leases"]))


class HistoryVerdictTest(unittest.TestCase):
    BASE = Version(0, 21, 7)

    def test_release_commit_owns_the_version_transition(self):
        changes = [
            Change("fix(db): close race", Version(0, 21, 8)),
            Change("test(db): cover cancellation", Version(0, 21, 8)),
        ]
        self.assertIsNone(history_verdict(self.BASE, changes))

    def test_a_later_chore_cannot_launder_a_missing_fix_bump(self):
        changes = [
            Change("fix(db): close race", self.BASE),
            Change("chore: bump version", Version(0, 21, 8)),
        ]
        failure = history_verdict(self.BASE, changes)
        self.assertIn("occurred in 'chore: bump version'", failure)

    def test_two_version_transitions_are_not_one_coherent_release(self):
        changes = [
            Change("fix(db): first fix", Version(0, 21, 8)),
            Change("fix(db): second fix", Version(0, 21, 9)),
        ]
        failure = history_verdict(self.BASE, changes)
        self.assertIn("expected 0.21.8", failure)


class CliHistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.command("git", "init", "-q")
        self.command("git", "config", "user.email", "test@example.com")
        self.command("git", "config", "user.name", "Test")
        self.write_version("0.21.7")
        self.commit("chore: establish base")
        self.base = self.command("git", "rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *command, check=True):
        return subprocess.run(
            command, cwd=self.repo, check=check, capture_output=True, text=True
        )

    def write_version(self, version):
        package = self.repo / "partyline"
        package.mkdir(exist_ok=True)
        (package / "__init__.py").write_text(
            f'__version__ = "{version}"\n', encoding="utf-8"
        )

    def commit(self, subject):
        self.command("git", "add", "partyline/__init__.py")
        self.command("git", "commit", "-q", "--allow-empty", "-m", subject)

    def policy(self):
        return self.command(
            sys.executable, str(SCRIPT), "--base", self.base, "--head", "HEAD", check=False
        )

    def test_cli_accepts_a_fix_that_owns_its_patch_bump(self):
        self.write_version("0.21.8")
        self.commit("fix(db): close race")
        result = self.policy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("patch", result.stdout)

    def test_cli_rejects_a_chore_that_launders_a_missing_fix_bump(self):
        self.commit("fix(db): close race")
        self.write_version("0.21.8")
        self.commit("chore: bump version")
        result = self.policy()
        self.assertEqual(result.returncode, 1)
        self.assertIn("occurred in 'chore: bump version'", result.stdout)


if __name__ == "__main__":
    unittest.main()
