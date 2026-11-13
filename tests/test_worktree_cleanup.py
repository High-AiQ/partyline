"""Recovery and deletion safety, using scratch repositories and databases only."""

import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.worktree_cleanup import cleanup
from partyline.worktree_lifecycle import sweep_orphaned_worktrees
from partyline.worktree_routes import list_kept, register_worktree_routes
from partyline.worktree_storage import latest_snapshot, reclaim_ignored, save_snapshot


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, capture_output=True, check=True).stdout


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "Tester")
        git(self.root, "config", "user.email", "test@example.com")
        (self.root / ".gitignore").write_text(".pytest_cache/\nnode_modules/\n*.ignored\n")
        (self.root / "tracked").write_bytes(b"original\x00bytes")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "initial")
        self.path = self.root / ".partyline-worktrees" / "kid"
        git(self.root, "worktree", "add", "-b", "line/kid", str(self.path))
        self.db = Db(Path(self.temp.name) / "test.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("root", "root", captain_mode="orchestrator")
        self.db.add_attachment("lead", "root", "lead", "raw", ["sh"], str(self.root))
        self.db.create_conversation("kid", "kid", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET cwd=?, parent_id='root' WHERE id='kid'", (str(self.path),))

    def run_cleanup(self, merged=True, **kwargs):
        return cleanup(self.db, str(self.root), str(self.path), merged, **kwargs)

    def ignored(self):
        (self.path / ".pytest_cache").mkdir(exist_ok=True)
        (self.path / ".pytest_cache" / "large").write_text("build")
        (self.path / "keep").write_text("real work")

    def test_snapshot_restores_staged_working_binary_untracked_and_deletions(self):
        (self.path / "tracked").write_bytes(b"staged\x00bytes")
        git(self.path, "add", "tracked")
        (self.path / "tracked").write_bytes(b"working\x00bytes")
        (self.path / ".gitignore").unlink()
        (self.path / "new").write_bytes(b"new\x00file")
        os.symlink("tracked", self.path / "link")
        before_index = git(self.path, "diff", "--cached", "--binary")
        before_work = git(self.path, "diff", "--binary")
        self.assertEqual(self.run_cleanup(), (True, None))
        saved = Path(latest_snapshot(self.db, str(self.root), str(self.path)))
        manifest = json.loads((saved / "manifest.json").read_text())
        git(self.root, "worktree", "add", "--detach", str(self.path), manifest["head"])
        git(self.path, "apply", "--index", str(saved / "index.patch"))
        git(self.path, "apply", str(saved / "worktree.patch"))
        with tarfile.open(saved / "untracked.tar") as archive:
            archive.extractall(self.path, filter="fully_trusted")
        self.assertEqual(git(self.path, "diff", "--cached", "--binary"), before_index)
        self.assertEqual(git(self.path, "diff", "--binary"), before_work)
        self.assertEqual((self.path / "new").read_bytes(), b"new\x00file")
        self.assertEqual(os.readlink(self.path / "link"), "tracked")

    def test_unmerged_keeps_changes_but_reclaims_ignored(self):
        self.ignored()
        (self.path / "tracked").write_text("changed")
        self.assertEqual(self.run_cleanup(False), (False, "unmerged commits"))
        self.assertFalse((self.path / ".pytest_cache").exists())
        self.assertTrue((self.path / "keep").exists())
        self.assertEqual((self.path / "tracked").read_text(), "changed")

    def test_nested_repository_inside_ignored_dependencies_survives(self):
        self.ignored()
        clone = self.path / "node_modules" / "deep" / "clone"
        clone.mkdir(parents=True)
        git(clone, "init", "-q")
        (clone / "important").write_text("unique")
        removed, reason = self.run_cleanup(force=True)
        self.assertFalse(removed)
        self.assertIn("contains repositories", reason)
        self.assertTrue((clone / "important").exists())
        self.assertFalse((self.path / ".pytest_cache").exists())

    def test_cap_keeps_worktree_and_records_reason_for_inventory(self):
        self.ignored()
        with patch("partyline.worktree_storage.SNAPSHOT_CAP", 2):
            removed, reason = self.run_cleanup()
        self.assertFalse(removed)
        self.assertIn("cap", reason)
        self.assertFalse((self.path / ".pytest_cache").exists())
        self.assertTrue((self.path / "keep").exists())
        entry = list_kept(self.db)[0]
        self.assertIn("cap", entry.kept_reason)
        self.assertEqual(entry.owner, "live")
        self.assertGreater(entry.size_bytes, 0)
        self.assertIsNone(latest_snapshot(self.db, str(self.root), str(self.path)))

    def test_sweep_does_not_delete_clean_unmerged_orphan(self):
        self.db._exec("DELETE FROM conversations WHERE id='kid'")
        git(self.path, "commit", "--allow-empty", "-qm", "unmerged")
        self.ignored()
        sweep_orphaned_worktrees(self.db)
        self.assertTrue(self.path.exists())
        self.assertFalse((self.path / ".pytest_cache").exists())
        self.assertEqual(list_kept(self.db)[0].owner, "none")

    def test_snapshot_failure_and_missing_git_keep_worktree(self):
        self.ignored()
        with patch("partyline.worktree_cleanup.save_snapshot", side_effect=OSError("disk full")):
            self.assertEqual(self.run_cleanup(), (False, "disk full"))
        (self.path / ".git").unlink()
        removed, reason = self.run_cleanup()
        self.assertFalse(removed)
        self.assertIn("orphaned", reason)
        self.assertTrue((self.path / "tracked").exists())
        self.assertTrue((self.path / "keep").exists())

    def test_untracked_special_file_is_refused(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("requires FIFO support")
        os.mkfifo(self.path / "pipe")
        self.assertFalse(self.run_cleanup()[0])
        self.assertTrue((self.path / "pipe").exists())

    def test_storage_inside_worktree_is_refused(self):
        self.db.path = str(self.path / "data.db")
        with self.assertRaisesRegex(ValueError, "inside"):
            save_snapshot(self.db, str(self.root), str(self.path))

    def test_ignored_reclamation_git_failure_is_harmless(self):
        self.ignored()
        with patch("partyline.worktree_storage._git", side_effect=OSError("git gone")):
            reclaim_ignored(str(self.path))
        self.assertTrue((self.path / ".pytest_cache").exists())

    def test_human_routes_confirmation_live_owner_and_snapshot_notice(self):
        app = FastAPI()
        runtime = type("Runtime", (), {"db": self.db})()
        register_worktree_routes(app, runtime)
        principal = Principal("machine", "worker")

        @app.middleware("http")
        async def identity(request, call_next):
            request.state.principal = principal
            return await call_next(request)

        with TestClient(app) as client:
            self.assertEqual(client.get("/api/worktrees").status_code, 403)
            self.assertEqual(client.post(
                "/api/worktrees/cleanup", json={"path": str(self.path)}).status_code, 403)
            principal = Principal("user", "person", user_id=1)
            self.assertEqual(client.get("/api/worktrees").json()[0]["owner"], "live")
            self.assertEqual(client.post(
                "/api/worktrees/cleanup", json={"path": str(self.path)}).status_code, 409)
            self.db.archive_conversation("kid")
            self.assertEqual(client.get("/api/worktrees").json()[0]["owner"], "archived")
            self.assertEqual(client.post(
                "/api/worktrees/cleanup", json={"path": "/outside"}).status_code, 404)
            self.assertEqual(client.post(
                "/api/worktrees/cleanup", json={"path": str(self.path), "force": True}).status_code, 400)
            self.ignored()
            with patch("partyline.worktree_routes.post_system_notice", return_value=None) as notice:
                result = client.post("/api/worktrees/cleanup", json={"path": str(self.path)})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json()["removed"])
            self.assertIsNotNone(result.json()["snapshot"])
            notice.assert_called_once()

    def test_force_preserves_unmerged_detached_tip(self):
        self.ignored()
        git(self.path, "checkout", "--detach")
        git(self.path, "commit", "--allow-empty", "-qm", "detached work")
        head = git(self.path, "rev-parse", "HEAD").strip()
        self.assertEqual(self.run_cleanup(False, force=True), (True, None))
        refs = git(self.root, "for-each-ref", "--format=%(objectname)",
                   "refs/partyline/preserved-worktrees/").splitlines()
        self.assertIn(head, refs)
        self.assertIsNone(latest_snapshot(self.db, str(self.root), str(self.path)))


    def test_tracked_ignored_file_and_untracked_files_survive_reclamation(self):
        (self.path / "tracked.ignored").write_text("tracked")
        git(self.path, "add", "-f", "tracked.ignored")
        self.ignored()
        reclaim_ignored(str(self.path))
        self.assertTrue((self.path / "tracked.ignored").exists())
        self.assertTrue((self.path / "keep").exists())
        self.assertFalse((self.path / ".pytest_cache").exists())

    def test_conflict_snapshot_is_refused(self):
        base = git(self.path, "rev-parse", "HEAD:tracked").decode().strip()
        git(self.path, "update-index", "--force-remove", "tracked")
        subprocess.run(["git", "update-index", "--index-info"], cwd=self.path,
                       input=f"100644 {base} 1\ttracked\n100644 {base} 2\ttracked\n".encode(),
                       check=True, capture_output=True)
        removed, reason = self.run_cleanup()
        self.assertFalse(removed)
        self.assertIn("unresolved merge", reason)
        self.assertTrue(self.path.exists())

    def test_binary_patch_cap_keeps_original_index_and_working_content(self):
        content = bytes(range(256)) * 20
        (self.path / "tracked").write_bytes(content)
        before = git(self.path, "ls-files", "--stage")
        with patch("partyline.worktree_storage.SNAPSHOT_CAP", 20):
            removed, reason = self.run_cleanup()
        self.assertFalse(removed)
        self.assertIn("cap", reason)
        self.assertEqual(git(self.path, "ls-files", "--stage"), before)
        self.assertEqual((self.path / "tracked").read_bytes(), content)

    def test_force_api_exact_confirmation(self):
        app = FastAPI()
        runtime = type("Runtime", (), {"db": self.db})()
        register_worktree_routes(app, runtime)

        @app.middleware("http")
        async def identity(request, call_next):
            request.state.principal = Principal("user", "person", user_id=1)
            return await call_next(request)

        self.db.archive_conversation("kid")
        self.ignored()
        with TestClient(app) as client:
            response = client.post("/api/worktrees/cleanup", json={
                "path": str(self.path), "force": True, "confirmation": str(self.path)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["removed"])
        self.assertIsNone(response.json()["snapshot"])


    def test_unaccepted_mirror_commit_keeps_a_clean_line_worktree(self):
        from partyline.worktree_lifecycle import archive_worktree_if_safe

        git(self.path, "commit", "--allow-empty", "-qm", "private work")
        private = git(self.path, "rev-parse", "HEAD").decode().strip()
        main = git(self.root, "rev-parse", "main").decode().strip()
        git(self.root, "update-ref", "refs/heads/line/kid", main)
        self.assertEqual(git(self.path, "status", "--porcelain"), b"")
        with patch("partyline.worktree_lifecycle.mirror_branch_ref", return_value=private):
            self.assertEqual(archive_worktree_if_safe(self.db, "kid"), (False, "unmerged commits"))
        self.assertTrue(self.path.exists())


    def test_missing_index_keeps_all_original_files(self):
        self.ignored()
        index = git(self.path, "rev-parse", "--git-path", "index").decode().strip()
        (self.path / index).unlink()
        self.assertEqual(self.run_cleanup(), (False, "cannot inspect worktree index"))
        self.assertTrue((self.path / "tracked").exists())
        self.assertTrue((self.path / "keep").exists())
        self.assertTrue((self.path / ".pytest_cache" / "large").exists())


    def test_inventory_and_merge_check_for_registered_task_workspace(self):
        from partyline.worktree_routes import known_worktrees, merged_state

        head = git(self.root, "rev-parse", "HEAD").decode().strip()
        self.db._exec("INSERT INTO task_workspaces VALUES(?,?,?,?,?)",
                      ("kid", str(self.root), str(self.path), "line/kid", head))
        self.assertTrue(any(item[1] == str(self.path) for item in known_worktrees(self.db)))
        owner = {**self.db.get_conversation("kid"), "cwd": str(self.path.parent / "top")}
        with patch("partyline.worktree_lifecycle.tip", return_value="invalid-commit"):
            self.assertFalse(merged_state(self.db, str(self.root), str(self.path), owner))
