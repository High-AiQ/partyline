"""Root disposal is explicit, preview-bound, recoverable and failure-safe."""

import json
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from partyline import auth_store
from partyline.retirement_git import inspect_git
from tests import test_retirement as base

_git = base._git


class ForcedRetirementTest(unittest.TestCase):
    setUp = base.RetirementTest.setUp
    child = base.RetirementTest.child
    dirty = base.RetirementTest.dirty
    unmerged = base.RetirementTest.unmerged
    retire = base.RetirementTest.retire

    def preview(self, child, headers=None, recursive=False):
        return self.client.get(
            f"/api/conversations/{child['id']}/retirement-preview",
            params={"include_children": str(recursive).lower()}, headers=headers or self.captain)

    def force(self, child, headers=None, **flags):
        response = self.preview(child, headers, flags.get("include_children", False))
        self.assertEqual(response.status_code, 200, response.text)
        return self.retire(child["id"], headers=headers, force_discard=True,
                           preview_token=response.json()["preview_token"], **flags)

    def test_snapshot_restores_tracked_untracked_and_superseded_history(self):
        child = self.child()
        self.dirty(child["cwd"], "tracked")
        _git("add", "tracked", cwd=child["cwd"])
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "superseded",
             cwd=child["cwd"])
        tip = _git("rev-parse", "HEAD", cwd=child["cwd"]).stdout.strip()
        self.dirty(child["cwd"], "new")
        with open(os.path.join(child["cwd"], "tracked"), "w") as stream:
            stream.write("updated")
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(os.path.exists(child["cwd"]))
        refs = response.json()["recovery_refs"][child["id"]]
        self.assertEqual(next(v for k, v in refs.items() if k.endswith("/branch")), tip)
        snapshot = next(v for k, v in refs.items() if k.endswith("/snapshot"))
        self.assertEqual(_git("show", f"{snapshot}:tracked", cwd=self.repo).stdout, "updated")
        self.assertEqual(_git("show", f"{snapshot}:new", cwd=self.repo).stdout, "wip")
        branches = _git("branch", "--list", f"line/{child['name']}", cwd=self.repo).stdout
        self.assertFalse(branches.strip())
        audit = self.db._exec("SELECT * FROM retirement_audit").fetchone()
        self.assertEqual(audit["decision"], "completed")
        self.assertEqual(json.loads(audit["principal"])["attachment_id"], "root-lead")
        self.assertIn("tracked", audit["evidence"])
        self.assertIn(tip, audit["recovery"])

    def test_explicit_flag_and_token_required(self):
        child = self.child()
        self.unmerged(child["cwd"])
        self.assertEqual(self.retire(child["id"]).status_code, 409)
        response = self.retire(child["id"], force_discard=True)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_same_path_new_bytes_make_preview_stale(self):
        child = self.child()
        self.dirty(child["cwd"])
        token = self.preview(child).json()["preview_token"]
        with open(os.path.join(child["cwd"], "scratch.txt"), "w") as stream:
            stream.write("new")
        response = self.retire(child["id"], force_discard=True, preview_token=token)
        self.assertEqual(response.status_code, 409)
        self.assertIn("stale", response.text)
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_token_is_bound_to_principal(self):
        child = self.child()
        token = self.preview(child).json()["preview_token"]
        response = self.retire(child["id"], headers=self.human, force_discard=True, preview_token=token)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.force(child, headers=self.human).status_code, 200)

    def test_non_root_captain_has_no_override(self):
        child = self.child()
        grand = self.child("grand", child["id"])
        self.db.add_attachment("mid-captain", child["id"], "mid", "fake", ["fake"], child["cwd"])
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='mid-captain'")
        headers = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "mid-captain")}
        preview = self.preview(grand, headers)
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.json()["force_allowed"])
        self.assertEqual(self.force(grand, headers=headers).status_code, 403)

    def test_self_and_cross_tree_are_denied(self):
        self.db.create_conversation("outside", "Outside")
        for target in ("root", "outside"):
            self.assertEqual(self.retire(target, force_discard=True).status_code, 403)
            self.assertEqual(self.preview({"id": target}).status_code, 403)

    def test_worker_cannot_preview_or_force(self):
        child = self.child()
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='root-lead'")
        self.assertEqual(self.preview(child).status_code, 403)
        self.assertEqual(self.retire(child["id"], force_discard=True).status_code, 403)

    def test_goal_and_recursion_require_explicit_flags(self):
        child = self.child()
        self.child("grand", child["id"])
        self.assertEqual(self.force(child).status_code, 409)
        self.db._exec("UPDATE conversations SET goal='save' WHERE id=?", (child["id"],))
        self.assertEqual(self.force(child, include_children=True).status_code, 409)
        self.assertEqual(self.db.get_conversation(child["id"])["goal"], "save")
        self.assertEqual(self.force(child, include_children=True, clear_goal=True).status_code, 200)

    def test_snapshot_failure_leaves_whole_tree_intact(self):
        child = self.child()
        grand = self.child("grand", child["id"])
        with patch("partyline.retirement_force.snapshot", side_effect=HTTPException(409, "snapshot failed")):
            response = self.force(child, include_children=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["archived_ids"], [])
        for line in (child, grand):
            self.assertTrue(os.path.isdir(line["cwd"]))
            self.assertFalse(self.db.get_conversation(line["id"])["archived_at"])
        self.assertEqual(self.db._exec("SELECT decision FROM retirement_audit").fetchone()[0], "failed")

    def test_recursive_cleanup_stops_on_first_failure(self):
        child = self.child()
        grand = self.child("grand", child["id"])
        with patch("partyline.retirement_force._remove", side_effect=HTTPException(409, "remove failed")):
            response = self.force(child, include_children=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["pending_ids"], [grand["id"], child["id"]])
        self.assertTrue(os.path.isdir(child["cwd"]))
        self.assertTrue(os.path.isdir(grand["cwd"]))

    def test_ignored_files_are_listed_but_not_snapshotted(self):
        child = self.child()
        with open(os.path.join(child["cwd"], ".gitignore"), "w") as stream:
            stream.write("ignored\n")
        self.dirty(child["cwd"], "ignored")
        evidence = self.preview(child).json()["lines"][0]["git"]
        self.assertEqual(evidence["ignored"]["paths"], ["ignored"])
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        refs = response.json()["recovery_refs"][child["id"]]
        snapshot = next(v for k, v in refs.items() if k.endswith("/snapshot"))
        paths = _git("ls-tree", "--name-only", snapshot, cwd=self.repo).stdout
        self.assertNotIn("ignored", paths)
        self.assertIn("ignored", self.db._exec("SELECT evidence FROM retirement_audit").fetchone()[0])

    def test_preview_limits_files_and_bytes(self):
        child = self.child()
        self.dirty(child["cwd"])
        for limit in ("MAX_FILES", "MAX_BYTES"):
            with patch(f"partyline.retirement_git.{limit}", 0):
                response = self.preview(child)
            self.assertEqual(response.status_code, 409)
            self.assertIn("limit", response.text)
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_git_unknown_refuses_instead_of_treating_as_clean(self):
        child = self.child()
        with patch("partyline.retirement_git._git", side_effect=OSError("git missing")):
            with self.assertRaises(HTTPException):
                inspect_git(self.db, child)

    def test_retirement_audit_is_readable_in_scope(self):
        child = self.child()
        self.assertEqual(self.force(child).status_code, 200)
        response = self.client.get(f"/api/conversations/{child['id']}/retirement-audit", headers=self.captain)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["decision"], "completed")

    def test_root_authority_is_rechecked_after_preview(self):
        child = self.child()
        token = self.preview(child).json()["preview_token"]
        self.db.create_conversation("new-root", "New root")
        self.db._exec("UPDATE conversations SET parent_id='new-root' WHERE id='root'")
        response = self.retire(child["id"], force_discard=True, preview_token=token)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_sibling_is_denied_to_non_root_captain(self):
        child = self.child()
        sibling = self.child("sibling")
        self.db.add_attachment("mid", child["id"], "mid", "fake", ["fake"], child["cwd"])
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='mid'")
        headers = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "mid")}
        self.assertEqual(self.retire(sibling["id"], headers=headers, force_discard=True).status_code, 403)

    def test_subtree_change_invalidates_token(self):
        child = self.child()
        token = self.preview(child, recursive=True).json()["preview_token"]
        grand = self.child("grand", child["id"])
        response = self.retire(child["id"], force_discard=True, include_children=True, preview_token=token)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(os.path.isdir(grand["cwd"]))

    def test_recursive_order_and_late_failure_preserve_parent(self):
        from partyline.retirement_force import _remove

        child = self.child()
        grand = self.child("grand", child["id"])
        calls = []

        def remove(state):
            calls.append(state["cwd"])
            if state["cwd"] == child["cwd"]:
                raise HTTPException(409, "parent failed")
            return _remove(state)

        with patch("partyline.retirement_force._remove", side_effect=remove):
            response = self.force(child, include_children=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(calls, [grand["cwd"], child["cwd"]])
        self.assertEqual(response.json()["archived_ids"], [grand["id"]])
        self.assertFalse(os.path.exists(grand["cwd"]))
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_snapshot_time_changes_are_refused_before_cleanup(self):
        from partyline.retirement_force import snapshot

        child = self.child()

        def changed(state, audit_id):
            refs = snapshot(state, audit_id)
            self.dirty(child["cwd"])
            return refs

        with patch("partyline.retirement_force.snapshot", side_effect=changed):
            response = self.force(child)
        self.assertEqual(response.status_code, 409)
        self.assertIn("changed during snapshot", response.text)
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_ignored_and_path_lists_are_bounded(self):
        child = self.child()
        for i in range(4):
            self.dirty(child["cwd"], f"file{i}")
        with patch("partyline.retirement_preview.DISPLAY", 2):
            state = self.preview(child).json()["lines"][0]["git"]["untracked"]
        self.assertEqual(state["count"], 4)
        self.assertTrue(state["truncated"])
        self.assertEqual(len(state["paths"]), 2)

    def test_large_files_use_metadata_and_symlinks_use_link_text(self):
        from partyline.retirement_git import file_evidence

        child = self.child()
        self.dirty(child["cwd"])
        os.symlink("scratch.txt", os.path.join(child["cwd"], "link"))
        with patch("partyline.retirement_git.HASH_BYTES", 1):
            rows, size = file_evidence(child["cwd"], ["scratch.txt", "link", "deleted"])
        self.assertEqual(rows[0], ["deleted", "deleted"])
        self.assertEqual(rows[1][-1], "scratch.txt")
        self.assertEqual(len(rows[2]), 6)
        self.assertGreater(size, 0)

    def test_dirty_auxiliary_assets_survive_retirement_and_sweep(self):
        from partyline.review_worktrees import sweep_review_worktrees
        from partyline.scratch_worktrees import sweep_scratch_worktrees

        child = self.child()
        sha = _git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        paths = []
        for folder, table in ((".review", "review_worktrees"), (".scratch", "scratch_worktrees")):
            path = os.path.join(self.repo, folder, sha)
            _git("worktree", "add", "--detach", path, sha, cwd=self.repo)
            self.db._exec(f"INSERT INTO {table}(path,conv_id,sha,created_at) VALUES(?,?,?,0)",
                          (path, child["id"], sha))
            self.dirty(path)
            paths.append(path)
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        sweep_review_worktrees(self.db, self.repo)
        sweep_scratch_worktrees(self.db, self.repo)
        for path in paths:
            self.assertTrue(os.path.isfile(os.path.join(path, "scratch.txt")))

    def test_live_process_needs_flag_and_unconfirmed_stop_preserves_worktree(self):
        child = self.child()
        self.db.add_attachment("worker", child["id"], "worker", "fake", ["fake"], child["cwd"], "owner")
        self.db.set_attachment_status("worker", "running", "owner")
        self.assertEqual(self.force(child).status_code, 409)
        response = self.force(child, stop_processes=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("unconfirmed", response.text)
        self.assertTrue(os.path.isdir(child["cwd"]))
        self.assertFalse(self.db.get_conversation(child["id"])["archived_at"])

    def test_root_can_explicitly_stop_mid_turn_process(self):
        child = self.child()
        self.db.add_attachment("worker", child["id"], "worker", "fake", ["fake"], child["cwd"], "owner")
        self.db.set_attachment_status("worker", "running", "owner")

        class Adapter:
            att = {"runtime_owner": "owner"}

            async def stop(adapter_self):
                self.db.set_attachment_status("worker", "detached", "owner")

        self.runtime.live["worker"] = Adapter()
        self.runtime.presence = type("Presence", (), {"is_working": lambda _self, _id: True})()
        response = self.force(child, stop_processes=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("worker", response.json()["stopped"])

    def test_changes_during_stop_keep_goal_and_files(self):
        child = self.child()
        self.db._exec("UPDATE conversations SET goal='save' WHERE id=?", (child["id"],))
        self.db.add_attachment("worker", child["id"], "worker", "fake", ["fake"], child["cwd"], "owner")
        self.db.set_attachment_status("worker", "running", "owner")

        class Adapter:
            att = {"runtime_owner": "owner"}

            async def stop(adapter_self):
                self.dirty(child["cwd"])
                self.db.set_attachment_status("worker", "detached", "owner")

        self.runtime.live["worker"] = Adapter()
        response = self.force(child, stop_processes=True, clear_goal=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("changed after process stop", response.text)
        self.assertEqual(self.db.get_conversation(child["id"])["goal"], "save")
        self.assertTrue(os.path.isfile(os.path.join(child["cwd"], "scratch.txt")))

    def test_snapshot_failure_from_git_does_not_touch_real_index(self):
        import subprocess
        from partyline.retirement_git import snapshot

        child = self.child()
        self.dirty(child["cwd"])
        _git("add", "scratch.txt", cwd=child["cwd"])
        before = _git("ls-files", "--stage", cwd=child["cwd"]).stdout
        state = inspect_git(self.db, child)
        with patch("partyline.retirement_git.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 1, "", "failure")):
            with self.assertRaisesRegex(HTTPException, "snapshot failed"):
                snapshot(state, "failed")
        self.assertEqual(_git("ls-files", "--stage", cwd=child["cwd"]).stdout, before)

    def test_mirror_only_tip_is_reported_and_preserved(self):
        child = self.child()
        self.unmerged(child["cwd"])
        mirror = _git("rev-parse", "HEAD", cwd=child["cwd"]).stdout.strip()
        _git("reset", "--hard", "HEAD~", cwd=child["cwd"])
        with patch("partyline.retirement_git.mirror_branch_ref", return_value=mirror):
            response = self.preview(child)
            self.assertEqual(response.json()["lines"][0]["git"]["mirror_tip"], mirror)
            response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(k.endswith("/mirror") and v == mirror
                            for k, v in response.json()["recovery_refs"][child["id"]].items()))

    def test_snapshot_is_unchanged_when_index_differs_from_working_files(self):
        child = self.child()
        self.dirty(child["cwd"])
        _git("add", "scratch.txt", cwd=child["cwd"])
        with open(os.path.join(child["cwd"], "scratch.txt"), "w") as stream:
            stream.write("latest")
        from partyline.retirement_git import snapshot

        before = _git("ls-files", "--stage", cwd=child["cwd"]).stdout
        refs = snapshot(inspect_git(self.db, child), "private-index-test")
        self.assertEqual(_git("ls-files", "--stage", cwd=child["cwd"]).stdout, before)
        sha = next(v for k, v in refs.items() if k.endswith("/snapshot"))
        self.assertEqual(_git("show", f"{sha}:scratch.txt", cwd=self.repo).stdout, "latest")
