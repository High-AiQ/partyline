"""Captain-shared task refs use scratch repositories and real Git mirrors."""

import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from partyline import git_fence
from partyline.task_workspaces import workspaces
from tests.orchestrator_fixture import TaskFixture, git
from tests.test_task_review_repositories import LayoutFixture


class ShareRefFixture(TaskFixture):
    async def running(self):
        self.fence = patch.object(git_fence, "FENCE_ROOT", os.path.join(self.directory.name, "fence"))
        self.fence.start()
        self.addCleanup(self.fence.stop)
        await self.create("none")
        self.workspace = workspaces(self.db, self.conv_id)[0]
        self.cwd = self.workspace["path"]
        self.gitdir = git_fence._worktree_gitdir(self.cwd)
        self.common = git_fence.common_gitdir(self.gitdir)
        self.mirror = git_fence.refresh_mirror(self.common, self.gitdir, self.conv_id)
        self.actor = self.captain
        self.endpoint = f"/api/conversations/{self.conv_id}/task/share-ref"

    def host_commit(self, message="later work"):
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def share(self, ref_or_sha, name="rescued", **extra):
        return self.client.post(self.endpoint, json={
            "ref_or_sha": ref_or_sha, "name": name, **extra})

    def notices(self):
        return [row for row in self.db.list_messages(self.conv_id)
                if row.get("audience_attachment_id") == self.worker.attachment_id]

    def metadata(self):
        head = Path(self.gitdir, "HEAD").read_bytes()
        packed = Path(self.mirror, "packed-refs")
        logs = Path(self.mirror, "logs")
        log_bytes = {str(path.relative_to(logs)): path.read_bytes()
                     for path in logs.rglob("*") if path.is_file()}
        return head, packed.read_bytes() if packed.exists() else None, log_bytes


class ShareRefTest(ShareRefFixture):
    async def test_running_task_receives_commit_and_refresh_preserves_it(self):
        await self.running()
        branch_ref = f"refs/heads/{self.workspace['branch']}"
        own_before = git_fence._read_ref(self.mirror, branch_ref)
        real_branch_before = git_fence._read_ref(self.common, branch_ref)
        metadata_before = self.metadata()
        notices_before = len(self.notices())
        base = git(self.repo, "rev-parse", "HEAD")
        sha = self.host_commit()
        git(self.repo, "branch", "captain-saved", sha)

        response = self.share("captain-saved")
        self.assertEqual(response.status_code, 200, response.text)
        ref = "refs/partyline/shared/rescued"
        self.assertEqual(response.json(), {
            "sha": sha, "ref": ref, "example": f"git merge {ref}", "repository": self.repo})
        self.assertEqual(git_fence._read_ref(self.mirror, ref), sha)
        self.assertIsNone(git_fence._read_ref(self.common, ref))
        self.assertEqual(git_fence._read_ref(self.mirror, branch_ref), own_before)
        self.assertEqual(git_fence._read_ref(self.common, branch_ref), real_branch_before)
        self.assertEqual(self.metadata(), metadata_before)
        notices = self.notices()[notices_before:]
        self.assertEqual(len(notices), 1)
        self.assertIn(ref, notices[0]["body"])
        self.assertIn(sha, notices[0]["body"])

        # A host ref with the same name must not replace the captain-shared
        # mirror value on the ordinary launch/resume preparation path.
        git(self.repo, "update-ref", ref, base)
        binds = git_fence.git_binds(self.cwd, self.conv_id, protected=self.workspace["branch"])
        objects = os.path.join(self.common, "objects")
        self.assertIn((objects, objects, False), binds)
        self.assertEqual(git_fence._read_ref(self.mirror, ref), sha)
        env = {**os.environ, "GIT_DIR": self.mirror, "GIT_OBJECT_DIRECTORY": objects}
        resolved = subprocess.run(["git", "rev-parse", "--verify", ref], env=env,
                                  capture_output=True, text=True, check=True).stdout.strip()
        kind = subprocess.run(["git", "cat-file", "-t", ref], env=env,
                              capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual((resolved, kind), (sha, "commit"))

    async def test_invalid_names_and_non_commits_are_refused_without_side_effects(self):
        await self.running()
        before = self.metadata()
        notices = len(self.notices())
        for name in ("", ".hidden", "bad..name", "nested/name", "white space", "bad*name", "x" * 65):
            with self.subTest(name=name):
                response = self.share("HEAD", name)
                self.assertIn(response.status_code, (400, 422), response.text)
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        for candidate in ("does-not-exist", tree):
            with self.subTest(candidate=candidate):
                response = self.share(candidate)
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.metadata(), before)
        self.assertEqual(len(self.notices()), notices)
        self.assertFalse(Path(self.mirror, "refs/partyline/shared").exists())

    async def test_option_like_empty_and_whitespace_refs_never_invoke_git(self):
        await self.running()
        before = self.metadata()
        notices = len(self.notices())
        with patch("partyline.orchestrator_share_ref.rev",
                   side_effect=AssertionError("Git must not be called")) as git_rev:
            for candidate in ("--output=/x", "-1", "", "two words", "two\nwords", "HEAD\0"):
                with self.subTest(candidate=candidate):
                    response = self.share(candidate)
                    self.assertEqual(response.status_code, 400, response.text)
        git_rev.assert_not_called()
        self.assertEqual(self.metadata(), before)
        self.assertEqual(len(self.notices()), notices)
        self.assertFalse(Path(self.mirror, "refs/partyline/shared").exists())

    async def test_existing_name_needs_same_sha_or_explicit_replace(self):
        await self.running()
        first = self.host_commit("first")
        second = self.host_commit("second")
        self.assertEqual(self.share(first).status_code, 200)
        notices = len(self.notices())
        conflict = self.share(second)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertIn("replace=true", conflict.json()["detail"])
        ref = "refs/partyline/shared/rescued"
        self.assertEqual(git_fence._read_ref(self.mirror, ref), first)
        self.assertEqual(len(self.notices()), notices)
        self.assertEqual(self.share(first).status_code, 200)
        self.assertEqual(self.share(second, replace=True).status_code, 200)
        self.assertEqual(git_fence._read_ref(self.mirror, ref), second)
        self.assertEqual(len(self.notices()), notices + 2)

    async def test_non_captain_and_stopped_task_are_refused(self):
        await self.running()
        self.actor = self.worker
        response = self.share("HEAD")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertFalse(Path(self.mirror, "refs/partyline/shared/rescued").exists())
        self.actor = self.captain
        self.db.set_attachment_status(self.worker.attachment_id, "exited",
                                      self.db.get_attachment(self.worker.attachment_id)["runtime_owner"])
        response = self.share("HEAD")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(Path(self.mirror, "refs/partyline/shared/rescued").exists())


class NestedRepositoryShareRefTest(LayoutFixture):
    async def test_repository_selects_a_recorded_nested_workspace(self):
        with patch.object(git_fence, "FENCE_ROOT", os.path.join(self.directory.name, "fence")):
            await self.placed("parent", policy="none")
            selected = self.repos["argon-backend"]
            workspace = next(row for row in workspaces(self.db, self.conv_id)
                             if row["repository"] == selected)
            gitdir = git_fence._worktree_gitdir(workspace["path"])
            mirror = git_fence.refresh_mirror(git_fence.common_gitdir(gitdir), gitdir, self.conv_id)
            sha = self.commit_in(selected, "saved backend")
            self.actor = self.captain
            response = self.client.post(f"/api/conversations/{self.conv_id}/task/share-ref", json={
                "ref_or_sha": "HEAD", "name": "backend", "repository": "argon-backend"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["repository"], selected)
            self.assertEqual(response.json()["sha"], sha)
            self.assertEqual(git_fence._read_ref(mirror, "refs/partyline/shared/backend"), sha)
            refused = self.client.post(f"/api/conversations/{self.conv_id}/task/share-ref", json={
                "ref_or_sha": "HEAD", "name": "other", "repository": self.repo})
            self.assertEqual(refused.status_code, 400, refused.text)


class SharedPackedRefTest(ShareRefFixture):
    async def test_refresh_preserves_packed_shared_entries(self):
        await self.running()
        sha = self.host_commit()
        ref = "refs/partyline/shared/packed"
        base = git(self.repo, "rev-parse", "HEAD^")
        Path(self.mirror, "packed-refs").write_text(f"{sha} {ref}\n")
        git(self.repo, "update-ref", ref, base)
        git(self.repo, "pack-refs", "--all")
        git_fence.refresh_mirror(self.common, self.gitdir, self.conv_id,
                                 protected=self.workspace["branch"])
        self.assertEqual(git_fence._read_ref(self.mirror, ref), sha)
        self.assertIn(f"{sha} {ref}\n", Path(self.mirror, "packed-refs").read_text())
