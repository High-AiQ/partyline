"""Retirement refuses in one answer and never leaves half a retirement behind."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from partyline import git_fence
from partyline.retirement_force import plan
from tests import test_retirement_force as base

_git = base._git


class SafetyFixture:
    """The forced-retirement fixture without re-running its tests here."""

    setUp = base.ForcedRetirementTest.setUp
    child = base.ForcedRetirementTest.child
    dirty = base.ForcedRetirementTest.dirty
    preview = base.ForcedRetirementTest.preview
    force = base.ForcedRetirementTest.force
    retire = base.ForcedRetirementTest.retire

    def live_worker(self, child):
        self.db.add_attachment("worker", child["id"], "worker", "fake", ["fake"],
                               child["cwd"], "owner")
        self.db.set_attachment_status("worker", "running", "owner")

        class Adapter:
            att = {"runtime_owner": "owner"}

            async def stop(adapter_self):
                self.db.set_attachment_status("worker", "detached", "owner")

        self.runtime.live["worker"] = Adapter()

    def worker_status(self):
        return self.db._exec("SELECT status FROM attachments WHERE id='worker'").fetchone()[0]

    def goal(self, child, text="finish it"):
        self.db._exec("UPDATE conversations SET goal=? WHERE id=?", (text, child["id"]))


class RefusalTest(SafetyFixture, unittest.TestCase):
    def test_guarded_refusal_names_every_flag_and_changes_nothing(self):
        child = self.child()
        self.live_worker(child)
        self.goal(child)

        response = self.retire(child["id"])

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["required_flags"], ["clear_goal", "stop_processes"])
        self.assertIn("stop_processes=true", response.json()["detail"])
        self.assertIn("clear_goal=true", response.json()["detail"])
        self.assertTrue(os.path.isdir(child["cwd"]))
        self.assertEqual(self.worker_status(), "running")
        self.assertIsNone(self.db.get_conversation(child["id"])["archived_at"])

    def test_force_refusal_names_every_missing_flag_and_touches_nothing(self):
        child = self.child()
        self.live_worker(child)
        self.goal(child)
        token = self.preview(child).json()["preview_token"]

        response = self.retire(child["id"], force_discard=True, preview_token=token)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("clear_goal=true, stop_processes=true", response.text)
        self.assertTrue(os.path.isdir(child["cwd"]))
        self.assertEqual(self.worker_status(), "running")
        self.assertEqual(self.db._exec("SELECT count(*) FROM retirement_audit").fetchone()[0], 0)

    def test_preview_names_every_flag_the_plan_needs(self):
        child = self.child()
        self.child("grand", child["id"])
        self.live_worker(child)
        self.goal(child)

        body = self.preview(child, recursive=True).json()

        self.assertEqual(body["required_flags"], [
            "clear_goal", "force_discard", "include_children", "stop_processes"])

    def test_uninspectable_git_state_stops_before_any_process_is_detached(self):
        child = self.child()
        self.live_worker(child)
        token = self.preview(child).json()["preview_token"]
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 3:  # plan (preview), plan (retire), then the per-line recheck
                raise HTTPException(409, "cannot inspect retirement Git state")
            return plan(*args, **kwargs)

        with patch("partyline.retirement_force.plan", side_effect=flaky):
            response = self.retire(child["id"], force_discard=True, preview_token=token,
                                   stop_processes=True)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("cannot inspect retirement Git state", response.text)
        self.assertTrue(os.path.isdir(child["cwd"]))
        self.assertEqual(self.worker_status(), "running")
        self.assertIsNone(self.db.get_conversation(child["id"])["archived_at"])


class AcceptedMirrorTipTest(SafetyFixture, unittest.TestCase):
    def fenced_task(self, child):
        """A task line whose host branch stayed at the base while its mirror holds the tip."""
        worktree = child["cwd"]
        gitdir = git_fence._worktree_gitdir(worktree)
        self.addCleanup(setattr, git_fence, "FENCE_ROOT", git_fence.FENCE_ROOT)
        git_fence.FENCE_ROOT = os.path.join(self.directory.name, "fence")
        mirror = git_fence._mirror_dir(git_fence.common_gitdir(gitdir), child["id"])
        base_sha = _git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.db._exec(
            "INSERT INTO task_workspaces(conv_id,repository,path,branch,base_sha) "
            "VALUES(?,?,?,?,?)", (child["id"], self.repo, worktree, "line/mid", base_sha))
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "the line's own work", cwd=worktree)
        accepted = _git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        git_fence._write_mirror_text(mirror, "refs/heads/line/mid", accepted + "\n")
        # the fence keeps the line's commits in the mirror: the real ref stays at the base
        _git("checkout", "-q", "--detach", accepted, cwd=worktree)
        _git("update-ref", "refs/heads/line/mid", base_sha, accepted, cwd=self.repo)
        return accepted

    def test_accepted_mirror_tip_finishes_the_retirement_and_keeps_the_host_branch(self):
        child = self.child()
        self.live_worker(child)
        accepted = self.fenced_task(child)

        response = self.force(child, stop_processes=True)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(os.path.exists(child["cwd"]))
        self.assertEqual(self.worker_status(), "detached")
        self.assertIsNotNone(self.db.get_conversation(child["id"])["archived_at"])
        kept = _git("rev-parse", "refs/heads/line/mid", cwd=self.repo).stdout.strip()
        self.assertEqual(kept, accepted)
        refs = response.json()["recovery_refs"][child["id"]]
        self.assertEqual(next(v for k, v in refs.items() if k.endswith("/mirror")), accepted)


class TrackedSymlinkTest(SafetyFixture, unittest.TestCase):
    def tracked_link(self, child):
        cwd = child["cwd"]
        Path(cwd, "AGENTS.md").write_text("rules\n")
        os.symlink("AGENTS.md", os.path.join(cwd, "CLAUDE.md"))
        _git("add", "-A", cwd=cwd)
        _git("commit", "-qm", "track the guide link", cwd=cwd)
        return cwd

    def test_a_tracked_symlink_previews_and_retires(self):
        child = self.child()
        self.tracked_link(child)

        preview = self.preview(child)

        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["required_flags"], ["force_discard"])
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(os.path.exists(child["cwd"]))

    def test_a_tracked_symlink_holding_a_directory_is_the_lines_own_content(self):
        child = self.child()
        cwd = self.tracked_link(child)
        os.unlink(os.path.join(cwd, "CLAUDE.md"))
        Path(cwd, "CLAUDE.md").mkdir()
        Path(cwd, "CLAUDE.md", "notes.md").write_text("work in progress\n")

        preview = self.preview(child)

        self.assertEqual(preview.status_code, 200, preview.text)
        line = preview.json()["lines"][0]["git"]
        self.assertIn("CLAUDE.md", line["tracked"]["paths"])
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(os.path.exists(cwd))

    def test_an_untracked_repository_directory_is_still_refused(self):
        child = self.child()
        embed = os.path.join(child["cwd"], "embed")
        os.makedirs(embed)
        _git("init", "-q", "-b", "main", ".", cwd=embed)

        response = self.preview(child)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("unsupported file type", response.text)
        self.assertTrue(os.path.isdir(child["cwd"]))
        self.assertIsNone(self.db.get_conversation(child["id"])["archived_at"])


if __name__ == "__main__":
    unittest.main()
