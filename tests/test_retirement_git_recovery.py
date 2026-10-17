"""Recovery must cover detached auxiliary history and index-only bytes, using real Git."""

import json
import os
import subprocess
import unittest
from pathlib import Path

from tests import test_retirement_auxiliary as fixtures

_git = fixtures.base._git


class RetirementGitRecoveryTest(unittest.TestCase):
    setUp = fixtures.RetirementAuxiliaryTest.setUp
    child = fixtures.RetirementAuxiliaryTest.child
    preview = fixtures.RetirementAuxiliaryTest.preview
    force = fixtures.RetirementAuxiliaryTest.force
    retire = fixtures.RetirementAuxiliaryTest.retire
    auxiliary = fixtures.RetirementAuxiliaryTest.auxiliary

    def commit(self, cwd, message="unique work"):
        _git("add", "-A", cwd=cwd)
        _git("commit", "-qm", message, cwd=cwd)
        return _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()

    def show(self, ref, path):
        return _git("show", f"{ref}:{path}", cwd=self.repo, text=False).stdout

    def test_unique_review_and_scratch_heads_are_disclosed_and_anchored_before_pruning(self):
        child = self.child()
        paths = self.auxiliary(child)
        heads = {}
        for table, path in paths.items():
            Path(path, "unique.txt").write_text(table)
            heads[table] = self.commit(path, table)
            self.assertFalse(_git("status", "--porcelain", cwd=path).stdout.strip())
            self.assertFalse(_git("for-each-ref", "--contains", heads[table], cwd=path).stdout.strip())
        line = self.preview(child).json()["lines"][0]
        for table, head in heads.items():
            entry = line["auxiliary_worktrees"][table][0]
            self.assertEqual(entry["head"], head)
            self.assertTrue(entry["unique"])
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        refs = response.json()["recovery_refs"][child["id"]]
        audit = json.loads(self.db._exec("SELECT recovery FROM retirement_audit").fetchone()[0])
        for table, head in heads.items():
            ref = next(ref for ref in refs if ref.endswith(f"/aux/{table}/0"))
            self.assertEqual(refs[ref], head)
            self.assertEqual(audit[child["id"]][ref], head)
            containing = _git("for-each-ref", "--format=%(refname)", "--contains", head,
                              cwd=self.repo).stdout.splitlines()
            self.assertIn(ref, containing)
            self.assertEqual(self.show(ref, "unique.txt"), table.encode())
            self.assertFalse(os.path.exists(paths[table]))

    def test_changed_review_and_scratch_heads_invalidate_previews(self):
        child = self.child()
        paths = self.auxiliary(child)
        for table, path in paths.items():
            with self.subTest(table=table):
                token = self.preview(child).json()["preview_token"]
                Path(path, "new.txt").write_text(table)
                self.commit(path, "new auxiliary HEAD")
                response = self.retire(child["id"], force_discard=True, preview_token=token)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("stale", response.text)
                self.assertTrue(os.path.isdir(child["cwd"]))
                self.assertTrue(os.path.isdir(path))
                self.assertEqual(self.db._exec("SELECT count(*) FROM retirement_audit").fetchone()[0], 0)

    def test_staged_and_working_bytes_have_separate_recovery_commits(self):
        child = self.child()
        staged, working, index_only = b"staged\x00\r\n\xff", b"working\x00\n\xfe", b"index only\x00\r\n"
        Path(child["cwd"], "both.bin").write_bytes(staged)
        Path(child["cwd"], "index-only.bin").write_bytes(index_only)
        _git("add", "both.bin", "index-only.bin", cwd=child["cwd"])
        Path(child["cwd"], "both.bin").write_bytes(working)
        Path(child["cwd"], "index-only.bin").unlink()
        preview = self.preview(child)
        self.assertIn("both the index", preview.json()["implications"])
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        refs = response.json()["recovery_refs"][child["id"]]
        index = next(ref for ref in refs if ref.endswith("/index"))
        snapshot = next(ref for ref in refs if ref.endswith("/snapshot"))
        self.assertEqual(self.show(index, "both.bin"), staged)
        self.assertEqual(self.show(index, "index-only.bin"), index_only)
        self.assertEqual(self.show(snapshot, "both.bin"), working)
        self.assertNotIn("index-only.bin", _git("ls-tree", "--name-only", snapshot, cwd=self.repo).stdout)

    def test_conflicted_index_refuses_before_removing_any_worktree_or_ref(self):
        child = self.child()
        paths = self.auxiliary(child)
        cwd = child["cwd"]
        Path(cwd, "conflict").write_text("base\n")
        self.commit(cwd, "base")
        branch = _git("branch", "--show-current", cwd=cwd).stdout.strip()
        _git("checkout", "-qb", "conflict-side", cwd=cwd)
        Path(cwd, "conflict").write_text("theirs\n")
        self.commit(cwd, "theirs")
        _git("checkout", "-q", branch, cwd=cwd)
        Path(cwd, "conflict").write_text("ours\n")
        tip = self.commit(cwd, "ours")
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            _git("merge", "conflict-side", cwd=cwd)
        self.assertIn("CONFLICT", failure.exception.stdout + failure.exception.stderr)
        stages = _git("ls-files", "--unmerged", cwd=cwd).stdout
        self.assertTrue(stages)
        index_path = _git(
            "rev-parse", "--path-format=absolute", "--git-path", "index", cwd=cwd).stdout.strip()
        index_bytes = Path(index_path).read_bytes()
        response = self.force(child)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("resolve or commit conflicted index before force retirement", response.text)
        self.assertEqual(_git("ls-files", "--unmerged", cwd=cwd).stdout, stages)
        self.assertEqual(Path(index_path).read_bytes(), index_bytes)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=cwd).stdout.strip(), tip)
        self.assertTrue(os.path.isdir(cwd))
        self.assertFalse(self.db.get_conversation(child["id"])["archived_at"])
        for path in paths.values():
            self.assertTrue(os.path.isdir(path))
        self.assertFalse(_git("for-each-ref", "refs/partyline/discarded/", cwd=self.repo).stdout.strip())
