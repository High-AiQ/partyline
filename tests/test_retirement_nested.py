"""Nested worktrees survive retirement through their owning repository's branch."""

import os
import socket
import unittest
from pathlib import Path

from fastapi import HTTPException

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
