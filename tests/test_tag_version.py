"""Real-git controls for automatic version tags."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tag_version.py"


class TagVersionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.repo = root / "repo"
        self.remote = root / "remote.git"
        self.command("git", "init", "--bare", "-q", str(self.remote), cwd=root)
        self.command("git", "init", "-q", str(self.repo), cwd=root)
        self.command("git", "config", "user.email", "test@example.com")
        self.command("git", "config", "user.name", "Test")
        self.command("git", "remote", "add", "origin", str(self.remote))
        self.write_version("0.21.7")
        self.commit("chore: establish base")
        self.base = self.sha()

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *command, cwd=None, check=True):
        return subprocess.run(
            command,
            cwd=cwd or self.repo,
            check=check,
            capture_output=True,
            text=True,
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

    def sha(self):
        return self.command("git", "rev-parse", "HEAD").stdout.strip()

    def tag(self):
        return self.command(
            sys.executable,
            str(SCRIPT),
            "--base",
            self.base,
            "--head",
            "HEAD",
            check=False,
        )

    def remote_target(self, tag):
        return self.command(
            "git",
            f"--git-dir={self.remote}",
            "rev-parse",
            f"refs/tags/{tag}^{{commit}}",
        ).stdout.strip()

    def test_unchanged_version_creates_no_tag(self):
        self.commit("docs: improve README")

        result = self.tag()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no tag needed", result.stdout)
        self.assertEqual(self.command("git", "tag", "--list").stdout, "")

    def test_changed_version_creates_annotated_remote_tag(self):
        self.write_version("0.21.8")
        self.commit("fix: repair routing")

        result = self.tag()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.remote_target("v0.21.8"), self.sha())
        tag_type = self.command("git", "cat-file", "-t", "v0.21.8").stdout.strip()
        self.assertEqual(tag_type, "tag")

    def test_existing_correct_tag_is_idempotent(self):
        self.write_version("0.21.8")
        self.commit("fix: repair routing")
        self.assertEqual(self.tag().returncode, 0)

        result = self.tag()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already points", result.stdout)

    def test_conflicting_tag_refuses_to_move(self):
        self.command("git", "tag", "-a", "v0.21.8", self.base, "-m", "wrong target")
        self.write_version("0.21.8")
        self.commit("fix: repair routing")

        result = self.tag()

        self.assertEqual(result.returncode, 1)
        self.assertIn("already points", result.stdout)
        self.assertEqual(
            self.command("git", "rev-parse", "v0.21.8^{commit}").stdout.strip(),
            self.base,
        )


if __name__ == "__main__":
    unittest.main()
