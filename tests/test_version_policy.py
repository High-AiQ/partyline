"""Controls for the pull-request release-version policy."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.version_policy import (
    Change,
    Version,
    extension_manifest_failure,
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

    def test_performance_commit_requires_a_patch_bump(self):
        self.assertEqual(required_bump(["perf(screen): reduce interaction latency"]), "patch")

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
            Change("fix(db): close race", self.BASE, Version(0, 21, 8)),
            Change("test(db): cover cancellation", Version(0, 21, 8), Version(0, 21, 8)),
        ]
        self.assertIsNone(history_verdict(self.BASE, Version(0, 21, 8), changes))

    def test_a_later_chore_cannot_launder_a_missing_fix_bump(self):
        changes = [
            Change("fix(db): close race", self.BASE, self.BASE),
            Change("chore: bump version", self.BASE, Version(0, 21, 8)),
        ]
        failure = history_verdict(self.BASE, Version(0, 21, 8), changes)
        self.assertIn("occurred in 'chore: bump version'", failure)

    def test_two_version_transitions_are_not_one_coherent_release(self):
        changes = [
            Change("fix(db): first fix", self.BASE, Version(0, 21, 8)),
            Change("fix(db): second fix", Version(0, 21, 8), Version(0, 21, 9)),
        ]
        failure = history_verdict(self.BASE, Version(0, 21, 9), changes)
        self.assertIn("expected 0.21.8", failure)

    def test_docs_bump_then_revert_is_not_no_release(self):
        changes = [
            Change("docs: bump by mistake", self.BASE, Version(0, 21, 8)),
            Change("chore: revert bump", Version(0, 21, 8), self.BASE),
        ]
        failure = history_verdict(self.BASE, self.BASE, changes)
        self.assertIn("must not contain a version transition", failure)

    def test_old_docs_commit_stays_valid_after_main_advances(self):
        old = Version(0, 21, 6)
        changes = [Change("docs: improve README", old, old)]
        self.assertIsNone(history_verdict(self.BASE, self.BASE, changes))

    def test_release_commit_must_own_the_current_head_version(self):
        old = Version(0, 21, 6)
        changes = [Change("fix(db): close race", old, self.BASE)]
        failure = history_verdict(self.BASE, Version(0, 21, 8), changes)
        self.assertIn("update the release commit against the current base", failure)


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
        return self.policy_between(self.base, "HEAD")

    def policy_between(self, base, head):
        return self.command(
            sys.executable, str(SCRIPT), "--base", base, "--head", head, check=False
        )

    def write_manifest(self, version):
        chrome = self.repo / "partyline_chrome"
        chrome.mkdir(exist_ok=True)
        (chrome / "manifest.json").write_text(f'{{"version": "{version}"}}\n')

    def setup_helper(self):
        helper = self.repo / "partyline_helper"
        helper.mkdir()
        (helper / "__init__.py").write_text('__version__ = "1.0.0"\n')
        (helper / "client.py").write_text("old\n")
        self.write_manifest("1.0.0")
        self.command("git", "add", "partyline_helper", "partyline_chrome")
        self.commit("chore: establish helper")
        self.base = self.command("git", "rev-parse", "HEAD").stdout.strip()
        return helper

    def test_helper_only_fix_requires_only_helper_patch(self):
        helper = self.setup_helper()
        (helper / "client.py").write_text("new\n")
        self.command("git", "add", "partyline_helper")
        self.commit("fix: repair helper")
        self.assertIn("helper", self.policy().stdout)
        self.assertEqual(self.policy().returncode, 1)
        (helper / "__init__.py").write_text('__version__ = "1.0.1"\n')
        self.write_manifest("1.0.1")
        self.command("git", "add", "partyline_helper", "partyline_chrome")
        self.command("git", "commit", "--amend", "--no-edit", "-q")
        self.assertEqual(self.policy().returncode, 0, self.policy().stdout)

    def test_helper_version_without_helper_change_is_rejected(self):
        helper = self.setup_helper()
        (helper / "__init__.py").write_text('__version__ = "1.0.1"\n')
        self.command("git", "add", "partyline_helper")
        self.commit("fix: unnecessary helper bump")
        self.assertEqual(self.policy().returncode, 1)

    def test_cli_rejects_a_helper_bump_that_leaves_the_manifest_behind(self):
        helper = self.setup_helper()
        (helper / "client.py").write_text("new\n")
        (helper / "__init__.py").write_text('__version__ = "1.0.1"\n')
        self.command("git", "add", "partyline_helper")
        self.commit("fix: repair helper")
        result = self.policy()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("partyline_chrome/manifest.json version is 1.0.0", result.stdout)
        self.assertIn("__version__ is 1.0.1", result.stdout)

    def test_cli_rejects_a_helper_without_a_manifest(self):
        helper = self.setup_helper()
        self.command("git", "rm", "-q", "-r", "partyline_chrome")
        self.commit("chore: drop manifest")
        self.base = self.command("git", "rev-parse", "HEAD").stdout.strip()
        (helper / "client.py").write_text("new\n")
        (helper / "__init__.py").write_text('__version__ = "1.0.1"\n')
        self.command("git", "add", "partyline_helper")
        self.commit("fix: repair helper")
        self.assertIn("is missing", self.policy().stdout)

    def test_cli_accepts_a_fix_that_owns_its_patch_bump(self):
        self.write_version("0.21.8")
        self.commit("fix(db): close race")
        result = self.policy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("patch", result.stdout)

    def test_cli_rejects_a_chore_that_launders_a_missing_fix_bump(self):
        (self.repo / "partyline" / "db.py").write_text("fixed\n")
        self.command("git", "add", "partyline/db.py")
        self.commit("fix(db): close race")
        self.write_version("0.21.8")
        self.commit("chore: bump version")
        result = self.policy()
        self.assertEqual(result.returncode, 1)
        self.assertIn("occurred in 'chore: bump version'", result.stdout)

    def test_cli_rejects_a_docs_bump_hidden_by_a_revert(self):
        self.write_version("0.21.8")
        self.commit("docs: bump by mistake")
        self.write_version("0.21.7")
        self.commit("chore: revert bump")

        result = self.policy()

        self.assertEqual(result.returncode, 1)
        self.assertIn("must not contain a version transition", result.stdout)

    def test_cli_accepts_an_old_docs_commit_after_main_advances(self):
        self.command("git", "switch", "-q", "-c", "docs")
        self.commit("docs: improve README")
        self.command("git", "switch", "-q", "-")
        self.write_version("0.21.8")
        self.commit("fix: advance main release")
        advanced_base = self.command("git", "rev-parse", "HEAD").stdout.strip()
        self.command("git", "switch", "-q", "docs")
        self.command("git", "merge", "-q", "--no-ff", advanced_base, "-m", "Merge main")

        result = self.policy_between(advanced_base, "HEAD")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no release", result.stdout)


def imported_partyline_modules(source, shared_module, root):
    """Find imports of project modules, including package-level import aliases."""
    import ast
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("partyline."))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module == "partyline":
                names = [alias.name for alias in node.names]
            elif node.level == 1 and shared_module and node.module is None:
                names = [alias.name for alias in node.names]
            else:
                names = []
            for name in names:
                if ((root / "partyline" / f"{name}.py").is_file()
                        or (root / "partyline" / name / "__init__.py").is_file() or name == "*"):
                    found.add(f"partyline.{name}")
            if node.level == 1 and shared_module and node.module:
                found.add(f"partyline.{node.module}")
            elif node.level == 0 and node.module and node.module.startswith("partyline."):
                found.add(node.module)
    paths = set()
    for name in found:
        path = name.replace(".", "/")
        if (root / path / "__init__.py").is_file():
            paths.add(path + "/__init__.py")
        else:
            paths.add(path + ".py")
    return paths


class ExtensionManifestTest(unittest.TestCase):
    helper = Version(1, 8, 6)

    def test_matching_version_passes(self):
        self.assertIsNone(extension_manifest_failure(self.helper, '{"version": "1.8.6"}'))

    def test_mismatch_names_both_files_and_both_values(self):
        failure = extension_manifest_failure(self.helper, '{"version": "1.8.4"}')
        for text in ("partyline_chrome/manifest.json", "partyline_helper/__init__.py", "1.8.4", "1.8.6"):
            self.assertIn(text, failure)

    def test_missing_manifest_fails(self):
        self.assertIn("is missing", extension_manifest_failure(self.helper, None))

    def test_unreadable_manifest_fails(self):
        for text in ("{not json", "[]", "{}", '{"version": 186}'):
            self.assertIsNotNone(extension_manifest_failure(self.helper, text), text)

    def test_checked_in_manifest_matches_the_checked_in_helper(self):
        root = Path(__file__).resolve().parents[1]
        helper = source_version((root / "partyline_helper" / "__init__.py").read_text())
        manifest = (root / "partyline_chrome" / "manifest.json").read_text()
        self.assertIsNone(extension_manifest_failure(helper, manifest))


class HelperPathTest(unittest.TestCase):
    def test_helper_imports_are_in_the_shared_path_list(self):
        from scripts.version_policy import HELPER_SHARED
        root = Path(__file__).resolve().parents[1]
        files = list((root / "partyline_helper").rglob("*.py")) + [root / p for p in HELPER_SHARED]
        for path in files:
            imported = imported_partyline_modules(path.read_text(), path.parent.name == "partyline", root)
            self.assertFalse(imported - HELPER_SHARED, f"{path}: {imported - HELPER_SHARED}")

    def test_package_and_relative_imports_are_checked(self):
        from scripts.version_policy import HELPER_SHARED
        root = Path(__file__).resolve().parents[1]
        for source, shared in (("from partyline import file_events", False),
                               ("from . import file_events", True),
                               ("from partyline.file_events import Changes", False)):
            self.assertEqual(imported_partyline_modules(source, shared, root) - HELPER_SHARED, set())
        for source, shared in (("from partyline import screen_hub as hub", False),
                               ("from . import screen_hub as hub", True),
                               ("from partyline.screen_hub import ScreenHub", False)):
            self.assertEqual(imported_partyline_modules(source, shared, root) - HELPER_SHARED,
                             {"partyline/screen_hub.py"})
        self.assertEqual(imported_partyline_modules("from partyline import adapters", False, root),
                         {"partyline/adapters/__init__.py"})
        self.assertEqual(imported_partyline_modules("from partyline import *", False, root),
                         {"partyline/*.py"})


if __name__ == "__main__":
    unittest.main()
