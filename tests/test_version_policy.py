"""Controls for the pull-request release-version policy."""

import unittest

from scripts.version_policy import Version, required_bump, source_version, verdict


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


if __name__ == "__main__":
    unittest.main()
