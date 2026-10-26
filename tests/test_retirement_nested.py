"""Nested worktrees survive retirement through their owning repository's branch."""

import os
import shutil
import socket
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from partyline import git_fence
from partyline.retirement_git import file_evidence, inspect_git
from tests.test_retirement_safety import SafetyFixture, _git


class NestedWorktreeTest(SafetyFixture, unittest.TestCase):
    def nested(self):
        child = self.child()
        owner = Path(self.directory.name, "owner")
        owner.mkdir()
        _git("init", "-q", "-b", "main", cwd=owner)
        _git("commit", "-qm", "root", "--allow-empty", cwd=owner)
        full = Path(child["cwd"], "nested")
        _git("worktree", "add", "-qb", "line/nested", str(full), cwd=owner)
        _git("commit", "-qm", "nested work", "--allow-empty", cwd=full)
        # Exclude without changing the outer repository's tracked files.
        with open(Path(self.repo, ".git", "info", "exclude"), "a") as stream:
            stream.write("\nnested/\n")
        return child, owner, full

    def mirrored(self, merged=True):
        child, owner, full = self.nested()
        fence = patch("partyline.git_fence.FENCE_ROOT", str(Path(self.directory.name, "fence")))
        fence.start()
        self.addCleanup(fence.stop)
        gitdir = git_fence._worktree_gitdir(str(full))
        common = git_fence.common_gitdir(gitdir)
        mirror = git_fence.refresh_mirror(common, gitdir, child["id"])
        git_fence.refresh_root_mirror(common, mirror)
        env = {**os.environ, "GIT_DIR": mirror, "GIT_WORK_TREE": str(full),
               "GIT_COMMON_DIR": mirror, "GIT_INDEX_FILE": str(Path(gitdir, "index")),
               "GIT_OBJECT_DIRECTORY": str(owner / ".git" / "objects")}
        Path(mirror, "HEAD").write_text("ref: refs/heads/line/nested\n")
        Path(full, "committed").write_text("private work")
        for args in (("add", "committed"), ("commit", "-qm", "private work")):
            subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                           cwd=full, env=env, capture_output=True,
                           text=True, check=True)
        tip = git_fence.mirror_branch_ref(str(full), child["id"], "line/nested")
        if merged:
            _git("merge", "--ff-only", tip, cwd=owner)
        return child, owner, full, tip

    def test_mirror_only_commits_merged_into_owner_retire(self):
        child, owner, full, tip = self.mirrored()
        head = _git("rev-parse", "HEAD", cwd=full).stdout.strip()
        self.assertNotEqual(head, tip)
        self.assertIn("A  committed", _git("status", "--porcelain", cwd=full).stdout)
        state = inspect_git(self.db, child)
        self.assertIn(["nested/", "nested-worktree", head, "line/nested", tip],
                      state["ignored_files"])
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(full.exists())
        self.assertEqual(_git("rev-parse", "main", cwd=owner).stdout.strip(), tip)

    def test_mirror_tip_ancestor_of_owner_branch_accepted(self):
        child, owner, _, _ = self.mirrored()
        _git("commit", "-qm", "later owner commit", "--allow-empty", cwd=owner)
        self.assertEqual(self.preview(child).status_code, 200)

    def test_unmerged_mirror_tip_refused(self):
        child, _, _, _ = self.mirrored(merged=False)
        self.assert_refused(child, "nested-worktree", "mirror tip not in the owning repository")

    def test_tip_objects_only_in_mirror_are_not_durable(self):
        child, owner, _, tip = self.mirrored(merged=False)
        store = git_fence.mirror_store(str(owner), child["id"])
        shutil.copytree(owner / ".git" / "objects", Path(store, "objects"))
        (owner / ".git" / "objects" / tip[:2] / tip[2:]).unlink()
        self.assert_refused(child, "nested-worktree", "mirror tip not in the owning repository")

    def test_untracked_edits_beyond_mirror_tip_refused(self):
        child, _, full, _ = self.mirrored()
        Path(full, "unfinished").write_text("keep me")
        self.assert_refused(child, "nested-worktree", "uncommitted edits beyond the mirror tip")

    def test_working_edits_beyond_mirror_tip_refused(self):
        child, _, full, _ = self.mirrored()
        Path(full, "committed").write_text("unfinished")
        self.assert_refused(child, "nested-worktree", "uncommitted edits beyond the mirror tip")

    def test_index_edits_beyond_mirror_tip_refused_even_when_files_match(self):
        child, _, full, _ = self.mirrored()
        _git("rm", "--cached", "committed", cwd=full)
        self.assert_refused(child, "nested-worktree", "uncommitted edits beyond the mirror tip")

    def test_mirror_tip_change_invalidates_preview_even_with_same_tree(self):
        child, owner, full, tip = self.mirrored()
        token = self.preview(child).json()["preview_token"]
        new_tip = _git("commit-tree", f"{tip}^{{tree}}", "-p", tip, "-m", "later", cwd=owner).stdout.strip()
        store = git_fence.mirror_store(str(owner), child["id"])
        Path(store, "refs", "heads", "line", "nested").write_text(new_tip + "\n")
        _git("merge", "--ff-only", new_tip, cwd=owner)
        response = self.retire(child["id"], force_discard=True, preview_token=token)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("stale", response.text)
        self.assertTrue(full.exists())

    def test_clean_nested_worktree_retires_and_prunes_registration(self):
        child, owner, full = self.nested()
        head = _git("rev-parse", "HEAD", cwd=full).stdout.strip()
        state = inspect_git(self.db, child)
        self.assertIn(["nested/", "nested-worktree", head, "line/nested"], state["ignored_files"])
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(Path(child["cwd"]).exists())
        self.assertNotIn(str(full), _git("worktree", "list", "--porcelain", cwd=owner).stdout)
        self.assertEqual(_git("rev-parse", "line/nested", cwd=owner).stdout.strip(), head)
        _git("cat-file", "-e", head, cwd=owner)

    def test_task_teardown_can_remove_nested_workspace_before_outer_worktree(self):
        child, owner, full = self.nested()
        head = _git("rev-parse", "HEAD", cwd=full).stdout.strip()
        self.db._exec(
            "INSERT INTO task_workspaces(conv_id,repository,path,branch,base_sha) "
            "VALUES(?,?,?,?,?)", (child["id"], str(owner), str(full), "line/nested", head))
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(Path(child["cwd"]).exists())
        self.assertNotIn(str(full), _git("worktree", "list", "--porcelain", cwd=owner).stdout)
        self.assertEqual(_git("rev-parse", "line/nested", cwd=owner).stdout.strip(), head)

    def test_dirty_nested_worktree_refused_with_path(self):
        child, _, full = self.nested()
        Path(full, "unfinished").write_text("keep me")
        self.assert_refused(child, "nested-worktree", "dirty")
        self.assertTrue(Path(full, "unfinished").exists())

    def test_detached_nested_worktree_refused_with_path(self):
        child, _, full = self.nested()
        _git("checkout", "--detach", "-q", cwd=full)
        self.assert_refused(child, "nested-worktree", "detached")

    def test_missing_owning_branch_refused_with_path(self):
        child, owner, _ = self.nested()
        _git("update-ref", "-d", "refs/heads/line/nested", cwd=owner)
        self.assert_refused(child, "nested-worktree", "no branch")

    def assert_refused(self, child, kind, reason):
        response = self.preview(child)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("nested/", response.text)
        self.assertIn(kind, response.text)
        self.assertIn(reason, response.text)
        self.assertTrue(Path(child["cwd"]).exists())

    def test_plain_untracked_directory_refused_with_path_and_kind(self):
        child = self.child()
        Path(child["cwd"], "nested").mkdir()
        with self.assertRaises(HTTPException) as caught:
            file_evidence(child["cwd"], ["nested/"])
        self.assertIn("nested/ (directory)", caught.exception.detail)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_fifo_refused_with_path_and_kind(self):
        child = self.child()
        os.mkfifo(Path(child["cwd"], "pipe"))
        with self.assertRaises(HTTPException) as caught:
            file_evidence(child["cwd"], ["pipe"])
        self.assertIn("pipe (fifo)", caught.exception.detail)

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "requires Unix sockets")
    def test_socket_refused_with_path_and_kind(self):
        child = self.child()
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(Path(child["cwd"], "socket")))
            with self.assertRaises(HTTPException) as caught:
                file_evidence(child["cwd"], ["socket"])
        self.assertIn("socket (socket)", caught.exception.detail)
