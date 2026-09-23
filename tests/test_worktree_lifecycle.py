"""Worktree removal SAFE test, captain-initiated archive, and the startup sweep."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server, worktree_lifecycle
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_worktree import WORKTREES_DIR, place_child
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.worktree_lifecycle import (
    archive_worktree_if_safe,
    sweep_orphaned_worktrees,
    worktree_removal_reason,
)
from partyline.features import overridden


def setUpModule():
    global _write_fence_off
    _write_fence_off = overridden(write_fence=False)
    _write_fence_off.__enter__()


def tearDownModule():
    _write_fence_off.__exit__(None, None, None)


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


class WorktreeLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_goal_route(app, self.runtime)
        self.spawned = []

        async def fake_start(att, **kwargs):
            self.spawned.append(att)
            return att

        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, self.directory.name + "/media"),
            None, {}, {}, fake_start,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(setattr, server, "runtime", server.runtime)
        self.addCleanup(setattr, server, "_start_attachment", server._start_attachment)
        server.runtime = self.runtime
        server._start_attachment = fake_start
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.directory.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.client.headers.update(self.human)

    def machine(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def child(self, parent, name, headers=None):
        made = self.client.post(f"/api/conversations/{parent}/children",
                                json={"name": name}, headers=headers or self.human)
        self.assertEqual(made.status_code, 201, made.text)
        return made.json()["conversation"]

    def captain(self, conv_id, name):
        att_id = f"{conv_id}-lead"
        self.db.add_attachment(att_id, conv_id, name, "fake", ["fake"], self.directory.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id=?", (att_id,))
        return self.machine(att_id)

    def _repo(self):
        repo = os.path.join(self.directory.name, "repo")
        os.makedirs(repo)
        _git("init", "-q", "-b", "main", cwd=repo)
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "root", cwd=repo)
        return repo

    def _root_on(self, repo):
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (repo,))

    # -- SAFE test -----------------------------------------------------------

    def test_merged_and_clean_worktree_is_removed(self):
        repo = self._repo()
        self._root_on(repo)
        placed = place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        self.assertIsNone(worktree_removal_reason(self.db, self.db.get_conversation("kid")))
        self.assertEqual(archive_worktree_if_safe(self.db, "kid"), (True, None))
        self.assertFalse(os.path.exists(placed["cwd"]))
        self.assertIn("line/kid", _git("branch", "--list", "line/kid", cwd=repo).stdout)

    def test_unmerged_commits_keep_the_worktree(self):
        repo = self._repo()
        self._root_on(repo)
        placed = place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "unmerged work", cwd=placed["cwd"])
        reason = worktree_removal_reason(self.db, self.db.get_conversation("kid"))
        self.assertEqual(reason, "unmerged commits")
        self.assertEqual(archive_worktree_if_safe(self.db, "kid"), (False, "unmerged commits"))
        self.assertTrue(os.path.isdir(placed["cwd"]))

    def test_uncommitted_changes_keep_the_worktree(self):
        repo = self._repo()
        self._root_on(repo)
        placed = place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        with open(os.path.join(placed["cwd"], "scratch.txt"), "w") as fh:
            fh.write("wip")
        reason = worktree_removal_reason(self.db, self.db.get_conversation("kid"))
        self.assertEqual(reason, "uncommitted changes")
        self.assertEqual(archive_worktree_if_safe(self.db, "kid"), (False, "uncommitted changes"))
        self.assertTrue(os.path.isdir(placed["cwd"]))

    def test_a_git_failure_reads_as_unmerged_never_as_safe(self):
        repo = self._repo()
        self._root_on(repo)
        place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        original = worktree_lifecycle._git

        def flaky(*args, cwd):
            if args[:1] == ("rev-list",):
                raise subprocess.SubprocessError("boom")
            return original(*args, cwd=cwd)

        with patch.object(worktree_lifecycle, "_git", side_effect=flaky):
            reason = worktree_removal_reason(self.db, self.db.get_conversation("kid"))
        self.assertEqual(reason, "unmerged commits")

    def test_the_repository_default_branch_is_used_not_whatever_is_checked_out(self):
        # A child merged into origin's default branch must read as safe even
        # when the root's own checkout has since moved to an unrelated branch.
        origin = os.path.join(self.directory.name, "origin.git")
        _git("init", "-q", "--bare", "-b", "main", origin, cwd=self.directory.name)
        repo = os.path.join(self.directory.name, "repo")
        _git("clone", "-q", origin, repo, cwd=self.directory.name)
        _git("checkout", "-q", "-b", "main", cwd=repo)
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "root", cwd=repo)
        _git("push", "-q", "-u", "origin", "main", cwd=repo)
        _git("remote", "set-head", "origin", "-a", cwd=repo)  # what a real clone sets
        self._root_on(repo)
        placed = place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "kid work", cwd=placed["cwd"])
        _git("push", "-q", "origin", "line/kid:main", cwd=placed["cwd"])
        _git("checkout", "-q", "-b", "wip", cwd=repo)  # root moves off the default branch
        self.assertEqual(_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip(), "wip")

        reason = worktree_removal_reason(self.db, self.db.get_conversation("kid"))

        self.assertIsNone(reason)

    def test_a_line_with_no_worktree_of_its_own_is_trivially_safe(self):
        # An inherited, non-git, or shared directory has nothing to keep.
        self.db.create_conversation("shares", "shares")
        self.db._exec("UPDATE conversations SET parent_id='root', cwd=? WHERE id='shares'",
                      (self.directory.name,))
        self.assertIsNone(worktree_removal_reason(self.db, self.db.get_conversation("shares")))

    # -- captain archive -------------------------------------------------------

    def test_a_captain_may_retire_a_finished_descendant_line(self):
        repo = self._repo()
        self._root_on(repo)
        mid = self.child("root", "mid", self.machine("root-lead"))
        resp = self.client.delete(f"/api/conversations/{mid['id']}", headers=self.machine("root-lead"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["archived"])
        self.assertTrue(resp.json()["worktree_removed"])
        self.assertIsNone(resp.json()["worktree_kept_reason"])
        self.assertFalse(os.path.exists(os.path.join(repo, WORKTREES_DIR, "mid")))

    def test_a_captain_cannot_retire_its_own_line(self):
        resp = self.client.delete("/api/conversations/root", headers=self.machine("root-lead"))
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_a_captain_cannot_retire_a_line_outside_its_tree(self):
        repo = self._repo()
        self._root_on(repo)
        mid = self.child("root", "mid", self.machine("root-lead"))
        other = self.child("root", "other", self.machine("root-lead"))
        resp = self.client.delete(f"/api/conversations/{other['id']}", headers=self.captain(mid["id"], "sol"))
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_a_captain_may_not_retire_a_line_with_live_processes(self):
        repo = self._repo()
        self._root_on(repo)
        mid = self.child("root", "mid", self.machine("root-lead"))
        worker = self.client.post(f"/api/conversations/{mid['id']}/attachments",
                                  json={"name": "gemini", "adapter": "raw", "command": "sh"},
                                  headers=self.machine("root-lead"))
        self.assertEqual(worker.status_code, 200, worker.text)
        self.db._exec("UPDATE attachments SET status='running' WHERE name='gemini'")
        resp = self.client.delete(f"/api/conversations/{mid['id']}", headers=self.machine("root-lead"))
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("live processes", resp.json()["detail"])

    def test_a_captain_may_not_retire_a_line_with_an_uncleared_goal(self):
        repo = self._repo()
        self._root_on(repo)
        mid = self.child("root", "mid", self.machine("root-lead"))
        self.db._exec("UPDATE conversations SET goal=? WHERE id=?", ("finish it", mid["id"]))
        resp = self.client.delete(f"/api/conversations/{mid['id']}", headers=self.machine("root-lead"))
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("goal", resp.json()["detail"])

    def test_a_captain_may_not_retire_a_line_whose_worktree_is_unsafe(self):
        repo = self._repo()
        self._root_on(repo)
        mid = self.child("root", "mid", self.machine("root-lead"))
        with open(os.path.join(mid["cwd"], "scratch.txt"), "w") as fh:
            fh.write("wip")
        resp = self.client.delete(f"/api/conversations/{mid['id']}", headers=self.machine("root-lead"))
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertIn("uncommitted changes", resp.json()["detail"])

    def test_a_person_may_retire_a_line_a_captain_could_not(self):
        repo = self._repo()
        self._root_on(repo)
        mid = self.child("root", "mid", self.machine("root-lead"))
        with open(os.path.join(mid["cwd"], "scratch.txt"), "w") as fh:
            fh.write("wip")
        resp = self.client.delete(f"/api/conversations/{mid['id']}")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["worktree_removed"])
        self.assertEqual(resp.json()["worktree_kept_reason"], "uncommitted changes")
        self.assertTrue(os.path.isdir(mid["cwd"]))

    def test_archiving_a_line_with_no_worktree_of_its_own_reports_neither(self):
        # A root line (or one on an inherited, non-git directory) has no
        # worktree of its own: nothing was removed, and there is no reason
        # to report — the dialog must not claim removal that never happened.
        resp = self.client.delete("/api/conversations/root")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["worktree_removed"])
        self.assertIsNone(resp.json()["worktree_kept_reason"])

    # -- purge stays unconditional --------------------------------------------

    def test_purge_removes_the_worktree_even_when_it_is_not_safe(self):
        repo = self._repo()
        self._root_on(repo)
        mid = self.child("root", "mid", self.machine("root-lead"))
        with open(os.path.join(mid["cwd"], "scratch.txt"), "w") as fh:
            fh.write("wip")
        archived = self.client.delete(f"/api/conversations/{mid['id']}")
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertTrue(os.path.isdir(mid["cwd"]))  # kept: dirty
        purged = self.client.delete(f"/api/conversations/{mid['id']}/purge")
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertFalse(os.path.exists(mid["cwd"]))

    # -- startup sweep ---------------------------------------------------------

    def test_startup_sweep_removes_clean_orphans_and_keeps_dirty_ones(self):
        repo = self._repo()
        self._root_on(repo)
        kid = place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        ghost = place_child(self.db, "root", self.db.create_conversation("ghost", "ghost")["id"])
        dirty_ghost = place_child(
            self.db, "root", self.db.create_conversation("dirty-ghost", "dirty ghost")["id"])
        with open(os.path.join(dirty_ghost["cwd"], "scratch.txt"), "w") as fh:
            fh.write("wip")
        # These rows are gone — by hand-editing or a purge interrupted before
        # the worktree removal step — but their directories remain.
        self.db._exec("DELETE FROM conversations WHERE id IN ('ghost', 'dirty-ghost')")

        sweep_orphaned_worktrees(self.db)

        self.assertTrue(os.path.isdir(kid["cwd"]))  # still a live line: untouched
        self.assertFalse(os.path.exists(ghost["cwd"]))  # clean orphan: removed
        self.assertTrue(os.path.isdir(dirty_ghost["cwd"]))  # dirty orphan: kept

    def test_startup_sweep_never_touches_an_archived_lines_worktree(self):
        repo = self._repo()
        self._root_on(repo)
        placed = place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        self.db.archive_conversation("kid")

        sweep_orphaned_worktrees(self.db)

        self.assertTrue(os.path.isdir(placed["cwd"]))

    def test_startup_sweep_finds_the_repo_even_when_no_child_line_survives(self):
        # The actual incident: every child line was purged, so the only
        # surviving trace of the repository is the root line's own
        # attachment cwd — the root's conversation row never carries one.
        repo = self._repo()
        self._root_on(repo)
        ghost = place_child(self.db, "root", self.db.create_conversation("ghost", "ghost")["id"])
        self.db._exec("DELETE FROM conversations WHERE id='ghost'")

        sweep_orphaned_worktrees(self.db)

        self.assertFalse(os.path.exists(ghost["cwd"]))


if __name__ == "__main__":
    unittest.main()
