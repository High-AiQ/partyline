"""The accepted hand-off: POST accept verifies a SHA, fast-forwards the line branch, records it."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import accept_sha as accept_sha_module
from partyline import auth_store, auth_tokens, server
from partyline import line_worktree as line_worktree_module
from partyline.accept_sha import (
    AcceptError,
    accept_sha,
    accepted_note,
    handoff_rider,
    register_accept_route,
)
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.staffing import staffing_report
from partyline.staffing_routes import staffing_router

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class AcceptShaTest(unittest.TestCase):
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
        app.include_router(staffing_router(self.runtime))

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

    def captain(self, conv_id, name="sol"):
        att_id = f"{conv_id}-lead"
        self.db.add_attachment(att_id, conv_id, name, "fake", ["fake"], self.directory.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id=?", (att_id,))
        return att_id

    def branch_head(self, branch="line/kid"):
        return _git("rev-parse", "--verify", "--quiet", branch, cwd=self.repo).stdout.strip()

    def commit(self, message, filename="code.txt"):
        with open(os.path.join(self.worktree, filename), "a") as fh:
            fh.write(message + "\n")
        _git("add", "-A", cwd=self.worktree)
        _identity("commit", "-q", "-m", message, cwd=self.worktree)
        return _git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip()

    def commit_detached(self, message, filename="code.txt"):
        _git("checkout", "-q", "--detach", cwd=self.worktree)
        sha = self.commit(message, filename)
        _git("checkout", "-q", "line/kid", cwd=self.worktree)
        return sha

    def commit_side(self, message, filename="code.txt"):
        _git("checkout", "-q", "-b", "side", cwd=self.worktree)
        sha = self.commit(message, filename)
        return sha

    def accept(self, sha, headers=None, conv_id=None):
        return self.client.post(
            f"/api/conversations/{conv_id or self.kid['id']}/accept",
            json={"sha": sha}, headers=headers or self.root_captain(),
        )

    def system_messages(self, conv_id):
        rows = self.db._exec(
            "SELECT body FROM messages WHERE conv_id=? AND sender_type='system' ORDER BY id",
            (conv_id,),
        ).fetchall()
        return [row["body"] for row in rows]

    # -- the happy paths -----------------------------------------------------

    def test_accept_fast_forwards_the_worktree_on_the_line_branch(self):
        self.commit("first")
        accepted = self.commit_detached("the real work")
        self.assertNotEqual(self.branch_head(), accepted)
        response = self.accept(accepted)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sha"], accepted)
        self.assertEqual(body["branch"], "line/kid")
        self.assertTrue(body["moved"])
        self.assertEqual(self.branch_head(), accepted)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip(), accepted)
        self.assertEqual(_git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.worktree).stdout.strip(),
                         "line/kid")
        self.assertIn(
            f"hand-off accepted by @terra: line/kid moved to {accepted[:12]}",
            " ".join(self.system_messages(self.kid["id"])),
        )

    def test_accept_moves_the_branch_when_the_worktree_sits_on_a_side_branch(self):
        self.commit("first")
        accepted = self.commit_side("work parked on a side branch")
        response = self.accept(accepted)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["moved"])
        self.assertEqual(self.branch_head(), accepted)
        self.assertEqual(_git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.worktree).stdout.strip(),
                         "side")  # the worktree itself is never switched

    def test_accept_still_moves_a_branch_whose_worktree_is_gone(self):
        self.commit("first")
        accepted = self.commit_side("work before the worktree went away")
        _git("worktree", "remove", "--force", self.worktree, cwd=self.repo)
        response = self.accept(accepted)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["moved"])
        self.assertEqual(self.branch_head(), accepted)

    def test_re_accepting_the_recorded_sha_is_a_clean_no_op(self):
        self.commit("first")
        sha = self.commit_detached("the real work")
        self.assertEqual(self.accept(sha).status_code, 200)
        again = self.accept(sha)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertFalse(again.json()["moved"])
        self.assertEqual(self.branch_head(), sha)

    # -- the record ----------------------------------------------------------

    def test_the_accepted_sha_is_on_the_staffing_board(self):
        self.commit("first")
        sha = self.commit_detached("the real work")
        self.accept(sha)
        report = staffing_report(self.db, "root")
        self.assertEqual(
            report["lines"],
            [{"id": self.kid["id"], "name": "kid", "accepted_sha": sha}],
        )
        seen = self.client.get("/api/conversations/root/staffing", headers=self.root_captain())
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertEqual(seen.json()["lines"][0]["accepted_sha"], sha)

    def test_the_accepted_sha_rides_the_checkout_line(self):
        self.commit("first")
        self.assertEqual(accepted_note(self.db, self.kid["id"]), "")
        sha = self.commit_detached("the real work")
        self.accept(sha)
        self.assertEqual(accepted_note(self.db, self.kid["id"]),
                         f" — accepted hand-off: {sha[:12]}")

    # -- the captain wake rider ------------------------------------------------

    def test_the_handoff_rider_surfaces_accepted_shas_and_worktrees(self):
        self.commit("first")
        self.assertEqual(handoff_rider(self.db, "root"), "")  # no hand-off anywhere yet
        sha = self.commit_detached("the real work")
        self.accept(sha)
        rider = handoff_rider(self.db, "root")
        self.assertIn("(hand-off: ", rider)
        self.assertIn(f"«kid» accepted {sha[:12]}", rider)
        self.assertIn(self.worktree, rider)
        own = handoff_rider(self.db, self.kid["id"])
        self.assertIn(f"accepted {sha[:12]}", own)
        self.assertIn(f"worktree {self.worktree}", own)

    def test_the_rider_omits_absent_values(self):
        self.db.create_conversation("loose", "loose")
        self.db._exec(
            "UPDATE conversations SET parent_id='root', accepted_sha=? WHERE id='loose'",
            ("a" * 40,),
        )
        rider = handoff_rider(self.db, "root")
        self.assertIn("«loose» accepted aaaaaaaaaaaa", rider)
        self.assertNotIn("worktree", rider.split("«loose»")[1])  # no cwd: no path claimed

    def test_a_worktree_alone_is_not_a_hand_off(self):
        # the kid is placed but nothing is accepted: no rider, here or above
        self.assertEqual(handoff_rider(self.db, self.kid["id"]), "")
        self.assertEqual(handoff_rider(self.db, "root"), "")

    def test_the_rider_rides_a_captain_wake(self):
        self.commit("first")
        from partyline.role_delivery import RoleState, bind_role_delivery

        sha = self.commit_detached("the real work")
        self.accept(sha)
        att = {"id": "root-lead", "digest_rider": lambda: "board"}
        lead = RoleState("lead", "root", None, ("read", "write", "assign", "create_child"))
        with patch("partyline.role_delivery.current_role", return_value=lead):
            bind_role_delivery(self.db, att)
            rider = att["digest_rider"]()
        self.assertIn("(hand-off: ", rider)
        self.assertIn(f"accepted {sha[:12]}", rider)

    # -- refusals ------------------------------------------------------------

    def test_an_unknown_or_non_hex_sha_is_refused(self):
        self.assertEqual(self.accept("deadbeef").status_code, 400)
        self.assertEqual(self.accept("main").status_code, 400)
        self.assertIsNone(self.db.get_conversation(self.kid["id"])["accepted_sha"])

    def test_a_branch_the_sha_cannot_fast_forward_to_is_refused(self):
        self.commit("first")
        side = self.commit_side("divergent work")
        _git("checkout", "-q", "line/kid", cwd=self.worktree)
        self.commit("later work on the line branch")
        response = self.accept(side)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("fast-forward", response.json()["detail"])
        self.assertNotEqual(self.branch_head(), side)

    def test_an_unrelated_history_is_refused(self):
        self.commit("first")
        stray = _identity("commit-tree", EMPTY_TREE, "-m", "stray", cwd=self.repo).stdout.strip()
        response = self.accept(stray)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("no history", response.json()["detail"])

    def test_a_sibling_line_s_commit_is_refused(self):
        # S2: the accepted SHA must sit on this line's own line of descent.
        self.commit("kid's own work")
        sib = self.client.post("/api/conversations/root/children", json={"name": "sib"})
        sib_wt = sib.json()["conversation"]["cwd"]
        _git("checkout", "-q", "-b", "side", cwd=sib_wt)
        with open(os.path.join(sib_wt, "s.txt"), "w") as fh:
            fh.write("sibling work\n")
        _git("add", "-A", cwd=sib_wt)
        _identity("commit", "-q", "-m", "sibling work", cwd=sib_wt)
        sibling_sha = _git("rev-parse", "HEAD", cwd=sib_wt).stdout.strip()
        response = self.accept(sibling_sha)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("fast-forwards", response.json()["detail"])
        self.assertNotEqual(self.branch_head(), sibling_sha)

    def test_accepting_work_the_parent_already_landed(self):
        # the parent fast-forwarded its own branch to the child's tip: the SHA
        # is this line's work by definition, even though the branch never moved
        sha = self.commit_detached("the real work")
        _git("merge", "--ff-only", sha, cwd=self.repo)
        self.assertEqual(self.branch_head("main"), sha)
        response = self.accept(sha)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.branch_head(), sha)

    def test_a_line_with_no_commits_of_its_own_refuses_a_foreign_sha(self):
        # S2, the zero-own-commit case: kid sits exactly at its branch point
        # with the parent, so a sibling's SHA is not this line's work — land
        # the line's own work on the branch first.
        sib = self.client.post("/api/conversations/root/children", json={"name": "sib"})
        sib_wt = sib.json()["conversation"]["cwd"]
        _git("checkout", "-q", "-b", "side", cwd=sib_wt)
        with open(os.path.join(sib_wt, "s.txt"), "w") as fh:
            fh.write("sibling work\n")
        _git("add", "-A", cwd=sib_wt)
        _identity("commit", "-q", "-m", "sibling work", cwd=sib_wt)
        sibling_sha = _git("rev-parse", "HEAD", cwd=sib_wt).stdout.strip()
        response = self.accept(sibling_sha)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("no commits of its own", response.json()["detail"])
        self.assertNotEqual(self.branch_head(), sibling_sha)
        own = self.commit("kid's first work")  # the remedy: land this line's work
        self.assertEqual(self.accept(own).status_code, 200)

    def test_a_parent_checkout_that_moved_ahead_does_not_block_the_line_s_own_work(self):
        self.commit("kid's own work")
        sha = self.commit_detached("the real work")
        _git("checkout", "-q", "main", cwd=self.repo)
        with open(os.path.join(self.repo, "main-moved.txt"), "w") as fh:
            fh.write("moved\n")
        _git("add", "-A", cwd=self.repo)
        _identity("commit", "-q", "-m", "main moved", cwd=self.repo)
        response = self.accept(sha)
        self.assertEqual(response.status_code, 200, response.text)

    def test_a_dirty_worktree_refuses_the_fast_forward_and_keeps_the_changes(self):
        self.commit("first")
        accepted = self.commit_detached("changes code.txt")
        with open(os.path.join(self.worktree, "code.txt"), "w") as fh:
            fh.write("uncommitted work\n")
        response = self.accept(accepted)
        self.assertEqual(response.status_code, 409, response.text)
        with open(os.path.join(self.worktree, "code.txt")) as fh:
            self.assertEqual(fh.read(), "uncommitted work\n")
        self.assertNotEqual(self.branch_head(), accepted)

    def test_a_line_outside_a_repository_is_refused(self):
        # a plain directory is neither a placed worktree nor a repository
        self.db.create_conversation("loose", "loose")
        self.db._exec("UPDATE conversations SET parent_id='root', cwd=? WHERE id='loose'",
                      (self.directory.name,))
        response = self.accept(self.commit_detached("work"), conv_id="loose")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("placed line worktree", response.json()["detail"])

    def test_a_line_whose_directory_is_gone_is_refused(self):
        self.db.create_conversation("ghost", "ghost")
        self.db._exec(
            "UPDATE conversations SET parent_id='root', cwd=? WHERE id='ghost'",
            ("/nonexistent/repo/.partyline-worktrees/ghost",),
        )
        self.db.create_conversation("gone", "gone")
        self.db._exec("UPDATE conversations SET parent_id='root', cwd=? WHERE id='gone'",
                      ("/nonexistent/plain",))
        sha = "abcdef0123456789"
        self.assertEqual(self.accept(sha, conv_id="ghost").status_code, 409)
        self.assertEqual(self.accept(sha, conv_id="gone").status_code, 409)

    def test_git_failures_surface_as_409(self):
        self.commit("first")
        original = line_worktree_module._git

        def no_merge_base(*args, cwd):
            if args[0] == "merge-base":
                raise subprocess.SubprocessError("boom")
            return original(*args, cwd=cwd)

        def branch_refuses(*args, cwd):
            if args[:1] == ("branch",):
                return subprocess.CompletedProcess(args, 1, "", "error: cannot force update")
            return original(*args, cwd=cwd)

        sha = self.commit_side("parked on a side branch")
        with patch.object(accept_sha_module, "_git", side_effect=no_merge_base), \
                patch.object(line_worktree_module, "_git", side_effect=no_merge_base):
            response = self.accept(sha)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("no history", response.json()["detail"])

        self.db._exec("UPDATE conversations SET accepted_sha=NULL WHERE id=?", (self.kid["id"],))
        with patch.object(accept_sha_module, "_git", side_effect=branch_refuses), \
                patch.object(line_worktree_module, "_git", side_effect=branch_refuses):
            response = self.accept(sha)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("cannot move line/kid", response.json()["detail"])
        self.assertNotEqual(self.branch_head(), sha)

    def test_accept_is_confined_to_placed_line_worktrees(self):
        # S1: a shared checkout's branch belongs to the person; partyline
        # never fast-forwards it.
        self.db.create_conversation("det", "det")
        self.db._exec("UPDATE conversations SET parent_id='root', cwd=? WHERE id='det'",
                      (self.repo,))
        main_before = _git("rev-parse", "main", cwd=self.repo).stdout.strip()
        response = self.accept(self.commit_detached("work"), conv_id="det")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("placed line worktree", response.json()["detail"])
        self.assertEqual(_git("rev-parse", "main", cwd=self.repo).stdout.strip(), main_before)

    def test_a_root_line_in_a_shared_checkout_cannot_accept(self):
        response = self.accept(self.commit_detached("work"), conv_id="root")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("placed line worktree", response.json()["detail"])

    def test_a_missing_branch_is_refused(self):
        sha = self.commit_detached("work")
        _git("worktree", "remove", "--force", self.worktree, cwd=self.repo)
        _git("branch", "-D", "line/kid", cwd=self.repo)
        response = self.accept(sha)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("no branch line/kid", response.json()["detail"])

    def test_accept_sha_404s_for_a_missing_line(self):
        with self.assertRaises(AcceptError) as raised:
            accept_sha(self.db, "missing", "abcdef1234567890")
        self.assertEqual(raised.exception.status_code, 404)

    # -- authorization ---------------------------------------------------------

    def test_only_the_parent_captain_or_the_line_captain_may_accept(self):
        self.commit("first")
        sha = self.commit_detached("the real work")
        kid_captain = self.machine(self.captain(self.kid["id"], "sol"))
        self.assertEqual(self.accept(sha, headers=kid_captain).status_code, 200)
        self.db._exec("UPDATE conversations SET accepted_sha=NULL WHERE id=?", (self.kid["id"],))
        self.assertEqual(self.branch_head(), sha)  # already there: the no-op path

        outsider = self.machine(self.captain(
            self.client.post("/api/conversations/root/children",
                             json={"name": "sib"}).json()["conversation"]["id"], "mo"))
        self.assertEqual(self.accept(sha, headers=outsider).status_code, 403)
        self.db.add_attachment("root-worker", "root", "dig", "fake", ["fake"], self.repo)
        self.assertEqual(self.accept(sha, headers=self.machine("root-worker")).status_code, 403)

    def test_nobody_accepts_across_two_levels(self):
        self.commit("kid's own work")  # grand is based on kid's tip, not the parent's
        grand = self.client.post(
            f"/api/conversations/{self.kid['id']}/children", json={"name": "grand"})
        self.assertEqual(grand.status_code, 201, grand.text)
        grand_worktree = grand.json()["conversation"]["cwd"]
        _git("merge", "--ff-only", "line/kid", cwd=grand_worktree)
        _git("checkout", "-q", "-b", "side", cwd=grand_worktree)
        with open(os.path.join(grand_worktree, "g.txt"), "w") as fh:
            fh.write("grand work\n")
        _git("add", "-A", cwd=grand_worktree)
        _identity("commit", "-q", "-m", "grand work", cwd=grand_worktree)
        sha = _git("rev-parse", "HEAD", cwd=grand_worktree).stdout.strip()
        self.assertEqual(self.accept(sha, conv_id=grand.json()["conversation"]["id"]).status_code,
                         403)  # the root captain is two levels up
        kid_captain = self.machine(self.captain(self.kid["id"], "sol"))
        self.assertEqual(self.accept(sha, headers=kid_captain).status_code, 200)


if __name__ == "__main__":
    unittest.main()
