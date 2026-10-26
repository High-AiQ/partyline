"""Captain reads expose mirror-only progress in outer and nested task repositories."""

import os
from unittest.mock import patch

from partyline import git_fence
from partyline.accept_sha import register_accept_route
from partyline.orchestrator_contracts import VerdictIn
from partyline.orchestrator_handles import task_line
from partyline.orchestrator_service import review_verdict
from partyline.orchestrator_store import tasks
from partyline.process_overview import process_overview
from partyline.task_workspaces import workspaces
from tests.orchestrator_fixture import git
from tests.test_task_workspaces import WorkspaceFixture


class WorkspaceVisibilityTest(WorkspaceFixture):
    async def mirrored_task(self):
        patcher = patch.object(git_fence, "FENCE_ROOT", os.path.join(self.directory.name, "fence"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.umbrella(True)
        await self.create("captain")
        self.mirrors = {}
        for item in workspaces(self.db, self.conv_id):
            gitdir = git_fence._worktree_gitdir(item["path"])
            self.mirrors[item["path"]] = git_fence.refresh_mirror(
                git_fence.common_gitdir(gitdir), gitdir, self.conv_id)

    def mirror_commit(self, item, subject):
        previous = git_fence.mirror_branch_ref(item["path"], self.conv_id, item["branch"])
        git(item["repository"], "update-ref", f"refs/heads/{item['branch']}",
            previous or item["base_sha"])
        git(item["path"], "commit", "-q", "--allow-empty", "-m", subject)
        sha = git(item["path"], "rev-parse", "HEAD")
        git_fence._write_mirror_text(self.mirrors[item["path"]],
                                     f"refs/heads/{item['branch']}", sha + "\n")
        git(item["repository"], "update-ref", f"refs/heads/{item['branch']}", item["base_sha"])
        return sha

    async def test_mirror_tips_and_unaccepted_commits_reach_every_captain_read_until_accept(self):
        await self.mirrored_task()
        shas = {item["repository"]: self.mirror_commit(item, "work in " + os.path.basename(item["path"]))
                for item in workspaces(self.db, self.conv_id)}

        listed = self.client.get("/api/conversations/root/tasks").json()[0]
        detail = self.client.get(f"/api/conversations/{self.conv_id}/task").json()
        overview = process_overview(self.runtime, "root").model_dump(mode="json")
        entry = next(line for line in overview["lines"] if line["id"] == self.conv_id)
        self.assertEqual({key: value for key, value in detail.items() if key != "repositories"},
                         {key: value for key, value in listed.items() if key != "repositories"})
        self.assertEqual(entry["workspaces"], listed["workspaces"])
        self.assertEqual(len(listed["workspaces"]), 3)
        for item in listed["workspaces"]:
            self.assertEqual(item["mirror_tip"], shas[item["repository"]])
            self.assertEqual(item["host_tip"], git(item["repository"], "rev-parse", "HEAD"))
            self.assertEqual(item["unaccepted_count"], 1)
            self.assertEqual(item["unaccepted_subjects"], ["work in " + os.path.basename(item["path"])])
            self.assertIsNone(item["accepted_sha"])

        await self.review()
        await review_verdict(self.runtime, self.captain, self.conv_id,
                             VerdictIn(verdict="approve", findings="fine"))
        register_accept_route(self.app, self.runtime)
        self.actor = self.captain
        accepted = self.client.post(f"/api/conversations/{self.conv_id}/accept",
                                    json={"sha": self.row()["sha"]})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        for item in tasks(self.db, "root", visibility=True)[0]["workspaces"]:
            self.assertEqual(item["host_tip"], shas[item["repository"]])
            self.assertEqual(item["accepted_sha"], shas[item["repository"]])
            self.assertEqual(item["unaccepted_count"], 0)
            self.assertEqual(item["unaccepted_subjects"], [])
        with (patch("partyline.workspace_visibility.os.path.isdir", return_value=False),
              patch("partyline.workspace_visibility.rev", side_effect=AssertionError("git called"))):
            self.assertEqual(tasks(self.db, "root", visibility=True)[0]["workspaces"], [])

    async def test_task_handle_resolution_does_not_spawn_git_but_listing_has_visibility(self):
        self.umbrella(False)
        row = await self.create("captain")
        with patch("partyline.workspace_visibility.rev", side_effect=AssertionError("git called")):
            self.assertEqual(task_line(self.db, self.captain, row["tag"]), self.conv_id)
        self.assertTrue(self.client.get("/api/conversations/root/tasks").json()[0]["workspaces"])

    async def test_unfenced_workspace_falls_back_to_the_host_tip(self):
        self.umbrella(False)
        await self.create("captain")
        sha = self.work("argon-backend")

        item = next(item for item in tasks(self.db, "root", visibility=True)[0]["workspaces"]
                    if item["repository"] == self.clones["argon-backend"])
        self.assertEqual(item["mirror_tip"], sha)
        self.assertEqual(item["host_tip"], sha)
        self.assertEqual(item["unaccepted_count"], 0)
        self.assertEqual(item["unaccepted_subjects"], [])

    async def test_commit_subjects_are_bounded_and_truncated(self):
        await self.mirrored_task()
        item = workspaces(self.db, self.conv_id)[0]
        for number in range(7):
            self.mirror_commit(item, f"commit {number} " + "x" * 150)

        visible = tasks(self.db, "root", visibility=True)[0]["workspaces"][0]
        self.assertEqual(visible["unaccepted_count"], 7)
        self.assertEqual(len(visible["unaccepted_subjects"]), 5)
        self.assertTrue(visible["unaccepted_subjects"][0].startswith("commit 6 "))
        self.assertTrue(all(len(subject) <= 120 for subject in visible["unaccepted_subjects"]))
        self.assertTrue(all(subject.endswith("…") for subject in visible["unaccepted_subjects"]))
