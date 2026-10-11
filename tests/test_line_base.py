"""The parent branch as the host sees it, and the line's fenced view of it (finding 2.11)."""

import os
import subprocess
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.accept_sha import register_accept_route
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_base import register_line_base_route, refresh_mirror_ref
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class LineBaseTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.repo)
        self.old_main = self.rev("main")
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_goal_route(app, self.runtime)
        register_accept_route(app, self.runtime)
        register_line_base_route(app, self.runtime)

        async def fake_start(att, **kwargs):
            return att

        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, self.directory.name + "/media"),
            None, {}, {}, fake_start,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(setattr, server, "runtime", server.runtime)
        server.runtime = self.runtime
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-lead")}
        self.client.headers.update(self.human)
        made = self.client.post("/api/conversations/root/children", json={"name": "kid"})
        self.assertEqual(made.status_code, 201, made.text)
        self.kid = made.json()["conversation"]
        self.worktree = self.kid["cwd"]

    def rev(self, name, cwd=None):
        return _git("rev-parse", "--verify", "--quiet", name,
                    cwd=cwd or self.repo).stdout.strip()

    def commit(self, message, filename="code.txt"):
        with open(os.path.join(self.worktree, filename), "a") as fh:
            fh.write(message + "\n")
        _git("add", "-A", cwd=self.worktree)
        _identity("commit", "-q", "-m", message, cwd=self.worktree)
        return _git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip()

    def move_host_main(self, message="main moved on the host"):
        with open(os.path.join(self.repo, "main.txt"), "a") as fh:
            fh.write(message + "\n")
        _git("add", "-A", cwd=self.repo)
        _identity("commit", "-q", "-m", message, cwd=self.repo)
        return self.rev("main")

    def write_mirror(self, conv_id, ref, sha):
        """One ref in a line's fence mirror, as a launch left it."""
        from partyline import git_fence

        self.addCleanup(setattr, git_fence, "FENCE_ROOT", git_fence.FENCE_ROOT)
        git_fence.FENCE_ROOT = os.path.join(self.directory.name, "fence")
        gitdir = git_fence._worktree_gitdir(self.worktree)
        mirror = git_fence._mirror_dir(git_fence.common_gitdir(gitdir), conv_id)
        git_fence._write_mirror_text(mirror, ref, sha + "\n")
        return mirror

    def mirrored(self, conv_id, ref):
        """The ref as the line's fence mirror holds it."""
        from partyline import git_fence

        gitdir = git_fence._worktree_gitdir(self.worktree)
        mirror = git_fence._mirror_dir(git_fence.common_gitdir(gitdir), conv_id)
        return git_fence._read_ref(mirror, ref)

    def test_refresh_refuses_to_touch_the_line_s_own_branch(self):
        tip = self.commit("kid's own work")
        self.write_mirror(self.kid["id"], "refs/heads/line/kid", tip)
        # the line's own branch can never be overwritten through this path,
        # not even by asking for it by name: the real ref never sees the
        # line's commits, and copying it in would erase them
        self.assertIsNone(
            refresh_mirror_ref(self.worktree, self.kid["id"], "line/kid"))
        self.assertEqual(self.mirrored(self.kid["id"], "refs/heads/line/kid"), tip)

    def test_base_reports_the_parent_sha_and_how_far_behind(self):
        new_main = self.move_host_main()
        tip = self.commit("kid's own work")
        seen = self.client.get(f"/api/conversations/{self.kid['id']}/base",
                               headers=self.captain)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertEqual(body["parent_branch"], "main")
        self.assertEqual(body["parent_sha"], new_main)
        self.assertEqual(body["line_base_sha"], self.old_main)
        self.assertEqual(body["behind"], 1)
        self.assertEqual(self.rev("line/kid"), tip)  # the line branch is real here

    def test_base_needs_a_parent_and_a_repository(self):
        self.assertEqual(self.client.get("/api/conversations/root/base",
                                         headers=self.captain).status_code, 409)
        self.assertEqual(self.client.get("/api/conversations/missing/base",
                                         headers=self.captain).status_code, 404)

    def test_refresh_base_updates_the_fenced_view_and_leaves_the_line_alone(self):
        tip = self.commit("kid's own work")
        self.write_mirror(self.kid["id"], "refs/heads/main", self.old_main)
        self.write_mirror(self.kid["id"], "refs/heads/line/kid", tip)
        new_main = self.move_host_main()
        # the fenced view still holds main at its launch-time value
        self.assertEqual(self.mirrored(self.kid["id"], "refs/heads/main"), self.old_main)
        seen = self.client.post(f"/api/conversations/{self.kid['id']}/refresh-base",
                                headers=self.captain)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertTrue(body["refreshed"])
        self.assertEqual(body["parent_sha"], new_main)
        self.assertEqual(body["seen_sha"], new_main)
        # the mirrored parent ref moved to today's main; the line's own state did not
        self.assertEqual(self.mirrored(self.kid["id"], "refs/heads/main"), new_main)
        self.assertEqual(self.mirrored(self.kid["id"], "refs/heads/line/kid"), tip)
        self.assertEqual(self.rev("line/kid"), tip)

    def test_an_accept_on_a_line_refreshes_its_children_s_views(self):
        grand = self.client.post(f"/api/conversations/{self.kid['id']}/children",
                                 json={"name": "grand"})
        self.assertEqual(grand.status_code, 201, grand.text)
        grand_id = grand.json()["conversation"]["id"]
        real = self.rev("line/kid")
        tip = self.commit("the reviewed work")
        self.write_mirror(self.kid["id"], "refs/heads/line/kid", tip)
        self.write_mirror(grand_id, "refs/heads/line/kid", real)  # grand launched earlier
        _git("update-ref", "refs/heads/line/kid", real, tip, cwd=self.repo)
        self.assertEqual(self.mirrored(grand_id, "refs/heads/line/kid"), real)
        accepted = self.client.post(f"/api/conversations/{self.kid['id']}/accept",
                                    json={"sha": tip}, headers=self.captain)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        # the grandchild's fenced view of its parent branch moved with the accept
        self.assertEqual(self.mirrored(grand_id, "refs/heads/line/kid"), tip)
        # the accepted line's own mirror held the tip all along and still does
        self.assertEqual(self.mirrored(self.kid["id"], "refs/heads/line/kid"), tip)
        self.assertEqual(self.rev("line/kid"), tip)


if __name__ == "__main__":
    unittest.main()
