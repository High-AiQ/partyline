"""Review worktrees: managed creation at <repo>/.review/<sha>, pruning at every exit."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline import review_worktrees as review_worktrees_module
from partyline.accept_sha import register_accept_route
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_worktree import WORKTREES_DIR
from partyline.media import MediaStore
from partyline.review_worktrees import (
    ReviewError,
    create_review_worktree,
    prune_review_worktrees,
    register_review_routes,
)
from partyline.runtime import ChatRuntime
from partyline.worktree_lifecycle import sweep_orphaned_worktrees


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class ReviewWorktreesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.repo)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_goal_route(app, self.runtime)
        register_accept_route(app, self.runtime)
        register_review_routes(app, self.runtime)

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
        self.client.headers.update(self.human)
        made = self.client.post("/api/conversations/root/children", json={"name": "kid"})
        self.assertEqual(made.status_code, 201, made.text)
        self.kid = made.json()["conversation"]
        self.worktree = self.kid["cwd"]

    def machine(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def root_captain(self):
        return self.machine("root-lead")

    def commit_detached(self, message):
        _git("checkout", "-q", "--detach", cwd=self.worktree)
        sha = self.commit_branch(message)
        _git("checkout", "-q", "line/kid", cwd=self.worktree)
        return sha

    def commit_branch(self, message):
        with open(os.path.join(self.worktree, "code.txt"), "a") as fh:
            fh.write(message + "\n")
        _git("add", "-A", cwd=self.worktree)
        _identity("commit", "-q", "-m", message, cwd=self.worktree)
        return _git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip()

    def create(self, sha, conv_id=None, headers=None):
        return self.client.post(
            f"/api/conversations/{conv_id or self.kid['id']}/review-worktrees",
            json={"sha": sha}, headers=headers or self.root_captain(),
        )

    def review_dir(self, sha):
        return os.path.join(self.repo, ".review", sha)

    def system_messages(self, conv_id):
        rows = self.db._exec(
            "SELECT body FROM messages WHERE conv_id=? AND sender_type='system' ORDER BY id",
            (conv_id,),
        ).fetchall()
        return [row["body"] for row in rows]

    # -- creation -------------------------------------------------------------

    def test_create_checks_the_sha_out_detached_and_records_it(self):
        sha = self.commit_detached("work under review")
        response = self.create(sha)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["sha"], sha)
        self.assertEqual(body["path"], self.review_dir(sha))
        self.assertTrue(os.path.isdir(self.review_dir(sha)))
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=self.review_dir(sha)).stdout.strip(), sha)
        self.assertEqual(
            _git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.review_dir(sha)).stdout.strip(),
            "HEAD")  # detached: a review checkout, not a branch
        listed = self.client.get(
            f"/api/conversations/{self.kid['id']}/review-worktrees", headers=self.root_captain())
        self.assertEqual([row["sha"] for row in listed.json()], [sha])
        self.assertIn(self.review_dir(sha), " ".join(self.system_messages(self.kid["id"])))
        # the managed directory is invisible to git status in the main checkout
        self.assertEqual(_git("status", "--porcelain", cwd=self.repo).stdout.strip(), "")

    def test_creating_the_same_sha_twice_returns_the_same_worktree(self):
        sha = self.commit_detached("work under review")
        first = self.create(sha)
        second = self.create(sha)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(first.json()["path"], second.json()["path"])
        listed = self.client.get(
            f"/api/conversations/{self.kid['id']}/review-worktrees", headers=self.root_captain())
        self.assertEqual(len(listed.json()), 1)

    def test_bad_requests_are_refused(self):
        sha = self.commit_detached("work under review")
        self.assertEqual(self.create("deadbeef").status_code, 400)
        self.assertEqual(self.create("main").status_code, 400)
        loose = "loose"
        self.db.create_conversation(loose, "loose")
        self.db._exec("UPDATE conversations SET parent_id='root', cwd=? WHERE id='loose'",
                      (self.directory.name,))
        self.assertEqual(self.create(sha, conv_id=loose).status_code, 409)

    def test_creation_needs_write_on_the_line(self):
        sha = self.commit_detached("work under review")
        self.db.add_attachment("kid-worker", self.kid["id"], "dig", "fake", ["fake"], self.repo)
        kid_worker = self.machine("kid-worker")
        self.assertEqual(self.create(sha, headers=kid_worker).status_code, 201)  # own line: write
        self.db.add_attachment("root-worker", "root", "dor", "fake", ["fake"], self.repo)
        outsider = self.machine("root-worker")  # a worker on the parent: no write on the child
        self.assertEqual(self.create(sha, headers=outsider).status_code, 403)

    # -- pruning at the lifecycle points ----------------------------------------

    def test_accept_prunes_the_accepted_sha_s_reviews_and_leaves_others(self):
        self.commit_branch("first")  # the line has work of its own before the hand-off
        first = self.commit_detached("first candidate")
        second = self.commit_detached("second candidate")
        self.create(first)
        self.create(second)
        self.assertTrue(os.path.isdir(self.review_dir(first)))
        accepted = self.client.post(
            f"/api/conversations/{self.kid['id']}/accept",
            json={"sha": first}, headers=self.root_captain())
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertFalse(os.path.isdir(self.review_dir(first)))
        self.assertTrue(os.path.isdir(self.review_dir(second)))  # still possibly mid-review
        listed = self.client.get(
            f"/api/conversations/{self.kid['id']}/review-worktrees", headers=self.root_captain())
        self.assertEqual([row["sha"] for row in listed.json()], [second])

    def test_retiring_the_line_prunes_its_review_worktrees(self):
        sha = self.commit_detached("work under review")
        self.create(sha)
        with open(os.path.join(self.review_dir(sha), "reviewer-notes.txt"), "w") as fh:
            fh.write("scratch")  # a review checkout is disposable, notes included
        retired = self.client.delete(
            f"/api/conversations/{self.kid['id']}", headers=self.root_captain())
        self.assertEqual(retired.status_code, 200, retired.text)
        self.assertFalse(os.path.isdir(self.review_dir(sha)))
        rows = self.db._exec("SELECT path FROM review_worktrees").fetchall()
        self.assertEqual(rows, [])

    def test_purging_the_line_prunes_its_review_worktrees(self):
        sha = self.commit_detached("work under review")
        self.create(sha)
        self.client.delete(f"/api/conversations/{self.kid['id']}", headers=self.root_captain())
        purged = self.client.delete(
            f"/api/conversations/{self.kid['id']}/purge", headers=self.root_captain())
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertFalse(os.path.isdir(self.review_dir(sha)))
        rows = self.db._exec("SELECT path FROM review_worktrees").fetchall()
        self.assertEqual(rows, [])

    # -- the startup sweep ------------------------------------------------------

    def test_the_sweep_removes_reviews_of_gone_lines_and_unrecorded_dirs(self):
        orphan_sha = self.commit_detached("reviewed once, line lost")
        made = create_review_worktree(self.db, self.kid["id"], orphan_sha)
        stray = self.commit_detached("reviewed through a record the server lost")
        created = create_review_worktree(self.db, self.kid["id"], stray)
        self.assertTrue(os.path.isdir(created["path"]))
        self.db._exec("DELETE FROM review_worktrees WHERE path=?", (created["path"],))
        self.db._exec("DELETE FROM conversations WHERE id=?", (self.kid["id"],))

        sweep_orphaned_worktrees(self.db)

        self.assertFalse(os.path.isdir(made["path"]))  # the line is gone: the review goes
        self.assertFalse(os.path.isdir(created["path"]))  # unrecorded hex dir: partyline's
        os.makedirs(os.path.join(self.repo, ".review", "notes"), exist_ok=True)
        sweep_orphaned_worktrees(self.db)
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".review", "notes")))

    def test_the_sweep_keeps_a_live_line_recorded_review(self):
        sha = self.commit_detached("review in progress")
        made = create_review_worktree(self.db, self.kid["id"], sha)
        sweep_orphaned_worktrees(self.db)
        self.assertTrue(os.path.isdir(made["path"]))

    def test_placed_worktrees_are_still_swept_normally(self):
        orphan = os.path.join(self.repo, WORKTREES_DIR, "orphan-line")
        _git("worktree", "add", "-b", "line/orphan-line", orphan, cwd=self.repo)
        sweep_orphaned_worktrees(self.db)
        self.assertFalse(os.path.isdir(orphan))

    # -- the guard paths ---------------------------------------------------------

    def test_prune_keeps_a_record_git_refuses_to_release(self):
        sha = self.commit_detached("work under review")
        made = create_review_worktree(self.db, self.kid["id"], sha)
        original = review_worktrees_module._git

        def locked(*args, cwd):
            if args[:2] == ("worktree", "remove"):
                return subprocess.CompletedProcess(args, 1, "", "error: is locked")
            return original(*args, cwd=cwd)

        with patch.object(review_worktrees_module, "_git", side_effect=locked):
            done = prune_review_worktrees(self.db, self.kid["id"])
        self.assertEqual(done, {"removed": 0, "kept": 1})
        self.assertTrue(os.path.isdir(made["path"]))
        self.assertEqual(self.db._exec("SELECT COUNT(*) c FROM review_worktrees").fetchone()["c"], 1)

    def test_prune_cleans_a_stale_record_and_unknown_lines_404(self):
        sha = self.commit_detached("work under review")
        made = create_review_worktree(self.db, self.kid["id"], sha)
        shutil.rmtree(made["path"])  # hand-deleted while the server was down
        self.assertEqual(prune_review_worktrees(self.db, self.kid["id"]),
                         {"removed": 1, "kept": 0})
        self.assertEqual(self.db._exec("SELECT COUNT(*) c FROM review_worktrees").fetchone()["c"], 0)
        with self.assertRaises(ReviewError) as raised:
            create_review_worktree(self.db, "missing", sha)
        self.assertEqual(raised.exception.status_code, 404)

    def test_a_symlinked_repo_root_does_not_confuse_the_review_records(self):
        sha = self.commit_detached("work under review")
        link = os.path.join(self.directory.name, "repo-link")
        os.symlink(self.repo, link)
        self.db._exec(
            "UPDATE conversations SET cwd=? WHERE id=?",
            (os.path.join(link, WORKTREES_DIR, "kid"), self.kid["id"]),
        )
        response = self.create(sha)
        self.assertEqual(response.status_code, 201, response.text)
        recorded = response.json()["path"]
        self.assertTrue(os.path.isdir(recorded))
        self.assertIn(f"worktree {recorded}",
                      _git("worktree", "list", "--porcelain", cwd=self.repo).stdout)
        self.assertEqual(prune_review_worktrees(self.db, self.kid["id"]),
                         {"removed": 1, "kept": 0})
        self.assertFalse(os.path.isdir(recorded))

    def test_a_failed_checkout_is_a_409(self):
        sha = self.commit_detached("work under review")
        original = review_worktrees_module._git

        def add_fails(*args, cwd):
            if args[:2] == ("worktree", "add"):
                return subprocess.CompletedProcess(args, 128, "", "fatal: not a repository")
            return original(*args, cwd=cwd)

        with patch.object(review_worktrees_module, "_git", side_effect=add_fails):
            response = self.create(sha)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("cannot create the review worktree", response.json()["detail"])

    def test_create_replaces_an_unregistered_directory_instead_of_adopting_it(self):
        sha = self.commit_detached("work under review")
        fake = self.review_dir(sha)
        os.makedirs(fake)
        with open(os.path.join(fake, "junk.txt"), "w") as fh:
            fh.write("not a checkout")
        response = self.create(sha)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(os.path.exists(os.path.join(fake, "junk.txt")))
        self.assertEqual(_git("rev-parse", "HEAD", cwd=fake).stdout.strip(), sha)
        self.assertIn(f"worktree {fake}",
                      _git("worktree", "list", "--porcelain", cwd=self.repo).stdout)

    def test_create_recreates_a_registered_checkout_left_at_the_wrong_commit(self):
        first = self.commit_detached("first candidate")
        made = create_review_worktree(self.db, self.kid["id"], first)
        second = self.commit_detached("a later commit")
        _git("checkout", "-q", "--detach", second, cwd=made["path"])  # drifted off the pin
        response = self.create(first)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=made["path"]).stdout.strip(), first)

    def test_a_stale_checkout_git_will_not_release_is_a_409(self):
        first = self.commit_detached("first candidate")
        made = create_review_worktree(self.db, self.kid["id"], first)
        second = self.commit_detached("a later commit")
        _git("checkout", "-q", "--detach", second, cwd=made["path"])
        with patch.object(review_worktrees_module, "remove_review_path", return_value=False):
            response = self.create(first)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("occupies", response.json()["detail"])

    # -- the documented CLI form --------------------------------------------------

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.review_worktree",
             "--database", f"{self.directory.name}/partyline.db", *args],
            capture_output=True, text=True, cwd=os.getcwd(),
        )

    def test_cli_create_list_prune(self):
        sha = self.commit_detached("work under review")
        made = self._cli("create", "--conversation", self.kid["id"], "--sha", sha)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertIn(self.review_dir(sha), made.stdout)
        self.assertTrue(os.path.isdir(self.review_dir(sha)))
        listed = self._cli("list", "--conversation", self.kid["id"])
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(sha, listed.stdout)
        pruned = self._cli("prune", "--conversation", self.kid["id"])
        self.assertEqual(pruned.returncode, 0, pruned.stderr)
        self.assertIn("removed 1 review worktrees", pruned.stdout)
        self.assertFalse(os.path.isdir(self.review_dir(sha)))
        self.assertEqual(self.db._exec("SELECT COUNT(*) c FROM review_worktrees").fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
