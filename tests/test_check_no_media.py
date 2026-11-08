"""Controls for scripts/check-no-media: no generated media enters the public repo."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-no-media"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class CheckNoMediaTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        self.git("init", "-q")
        self.commit({"README.md": b"hello\n"})
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=ENV, check=True,
                              capture_output=True, text=True).stdout

    def commit(self, files, remove=()):
        for name, data in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in remove:
            self.git("rm", "-q", name)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        return self.git("rev-parse", "HEAD").strip()

    def run_check(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo, env=ENV,
                                capture_output=True, text=True)
        return result.returncode, result.stdout

    def check_range(self):
        return self.run_check("--base", self.base, "--head", "HEAD")

    def test_allowed_media_paths_pass(self):
        self.commit({"media/shot.jpg": b"jpg", "tests/fixtures/in/card.png": b"png"})
        code, out = self.check_range()
        self.assertEqual(code, 0, out)

    def test_png_in_skills_fails_with_path_commit_and_hint(self):
        sha = self.commit({"skills/verify-visual-change/shot.png": b"png"})
        code, out = self.check_range()
        self.assertEqual(code, 1)
        self.assertIn("skills/verify-visual-change/shot.png", out)
        self.assertIn(sha[:12], out)
        self.assertIn("upload screenshots", out)
        self.assertIn("/var/tmp", out)

    def test_every_media_family_fails(self):
        names = ["a.JPEG", "a.webp", "a.hdr", "a.mov", "a.flac", "a.glb", "a.usdz", "a.blend",
                 "a.pdf", "a.zip", "a.tar", "a.tar.gz", "a.7z", "dir/a.heic"]
        self.commit({name: b"x" for name in names})
        code, out = self.check_range()
        self.assertEqual(code, 1)
        for name in names:
            self.assertIn(name, out)

    def test_added_then_deleted_across_two_commits_still_fails(self):
        added = self.commit({"tests/evidence/proof.png": b"png"})
        self.commit({}, remove=["tests/evidence/proof.png"])
        self.assertFalse((self.repo / "tests/evidence/proof.png").exists())
        code, out = self.check_range()
        self.assertEqual(code, 1)
        self.assertIn("tests/evidence/proof.png", out)
        self.assertIn(added[:12], out)

    def test_modifying_an_existing_media_file_fails(self):
        self.commit({"docs/old.png": b"1"})
        self.base = self.git("rev-parse", "HEAD").strip()
        self.commit({"docs/old.png": b"2"})
        self.assertEqual(self.check_range()[0], 1)

    def test_large_non_media_file_fails_but_small_text_passes(self):
        self.commit({"docs/notes.md": b"plain text\n"})
        self.assertEqual(self.check_range()[0], 0)
        self.commit({"data/dump.bin": b"\0" * (1024 * 1024 + 1)})
        code, out = self.check_range()
        self.assertEqual(code, 1)
        self.assertIn("data/dump.bin", out)

    def test_file_at_the_limit_passes(self):
        self.commit({"data/edge.bin": b"\0" * (1024 * 1024)})
        self.assertEqual(self.check_range()[0], 0)

    def test_allowlisted_files_have_a_cap(self):
        self.commit({"media/video.jpg": b"\0" * (5 * 1024 * 1024 + 1)})
        self.assertEqual(self.check_range()[0], 1)

    def test_committed_build_may_be_large_but_never_media_or_huge(self):
        self.commit({"partyline/static/assets/model.wasm": b"\0" * (2 * 1024 * 1024)})
        self.assertEqual(self.check_range()[0], 0)
        self.commit({"partyline/static/assets/leak.png": b"png"})
        self.assertEqual(self.check_range()[0], 1)
        self.base = self.git("rev-parse", "HEAD").strip()
        self.commit({"partyline/static/assets/huge.wasm": b"\0" * (16 * 1024 * 1024 + 1)})
        self.assertEqual(self.check_range()[0], 1)

    def test_deleting_media_is_not_flagged(self):
        self.commit({"media/keep.png": b"png"})
        self.base = self.git("rev-parse", "HEAD").strip()
        self.commit({}, remove=["media/keep.png"])
        self.assertEqual(self.check_range()[0], 0)

    def test_merged_branch_commits_are_all_checked(self):
        self.git("checkout", "-q", "-b", "side")
        bad = self.commit({"shot.png": b"png"})
        self.commit({}, remove=["shot.png"])
        self.git("checkout", "-q", "-")
        self.commit({"docs/x.md": b"x"})
        self.git("merge", "-q", "--no-ff", "-m", "merge", "side")
        code, out = self.check_range()
        self.assertEqual(code, 1)
        self.assertIn(bad[:12], out)

    def test_local_mode_covers_staged_files_and_whole_history_without_origin(self):
        (self.repo / "staged.png").write_bytes(b"png")
        self.git("add", "staged.png")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("staged.png", out)
        self.git("rm", "-q", "-f", "staged.png")
        self.assertEqual(self.run_check()[0], 0)
        self.commit({"old.png": b"png"})
        self.assertEqual(self.run_check()[0], 1)

    def test_local_mode_checks_only_commits_beyond_origin_main(self):
        self.commit({"old.png": b"png"})
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(self.run_check()[0], 0)
        self.commit({"new.png": b"png"})
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("new.png", out)
        self.assertNotIn("old.png", out)

    def test_a_bad_revision_is_an_error_not_a_pass(self):
        code, out = self.run_check("--base", "nope", "--head", "HEAD")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
