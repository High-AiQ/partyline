"""Child creation from a stale checkout: the deliberate base:"upstream" cut, default unchanged."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline import checkout_health as checkout_health_module
from partyline import line_worktree as line_worktree_module
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_worktree import place_child
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class ChildBaseTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        origin = os.path.join(self.directory.name, "origin.git")
        _git("init", "-q", "--bare", "-b", "main", origin, cwd=self.directory.name)
        self.repo = os.path.join(self.directory.name, "repo")
        _git("clone", "-q", origin, self.repo, cwd=self.directory.name)
        _git("checkout", "-q", "-b", "main", cwd=self.repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.repo)
        _git("push", "-q", "-u", "origin", "main", cwd=self.repo)
        _git("remote", "set-head", "origin", "-a", cwd=self.repo)
        self.origin_main = lambda: _git(
            "rev-parse", "main", cwd=origin).stdout.strip()
        self.local_main = lambda: _git("rev-parse", "main", cwd=self.repo).stdout.strip()

        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_goal_route(app, self.runtime)

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
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-lead")}

    def advance_origin(self):
        """Move origin/main ahead of the parent checkout, which never pulls."""
        pusher = os.path.join(self.directory.name, "pusher")
        _git("clone", "-q", os.path.join(self.directory.name, "origin.git"), pusher,
             cwd=self.directory.name)
        with open(os.path.join(pusher, "new.txt"), "w") as fh:
            fh.write("later work\n")
        _git("add", "-A", cwd=pusher)
        _identity("commit", "-q", "-m", "later work", cwd=pusher)
        _git("push", "-q", "origin", "main", cwd=pusher)

    def child(self, name, headers=None, **fields):
        made = self.client.post(
            "/api/conversations/root/children", json={"name": name, **fields},
            headers=headers or self.human)
        return made

    def child_head(self, conversation):
        return _git("rev-parse", "HEAD", cwd=conversation["cwd"]).stdout.strip()

    def system_messages(self, conv_id):
        rows = self.db._exec(
            "SELECT body FROM messages WHERE conv_id=? AND sender_type='system' ORDER BY id",
            (conv_id,),
        ).fetchall()
        return [row["body"] for row in rows]

    def test_a_machine_cannot_cut_a_child_from_a_stale_checkout_by_default(self):
        self.advance_origin()
        made = self.child("kid", headers=self.captain)
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("behind", made.json()["detail"])

    def test_upstream_base_cuts_from_the_fetched_default(self):
        self.advance_origin()
        made = self.child("kid", headers=self.captain, base="upstream")
        self.assertEqual(made.status_code, 201, made.text)
        conversation = made.json()["conversation"]
        self.assertEqual(self.child_head(conversation), self.origin_main())
        self.assertNotEqual(self.child_head(conversation), self.local_main())
        self.assertEqual(
            _git("rev-parse", "line/kid", cwd=self.repo).stdout.strip(), self.origin_main())
        self.assertIn("cut from origin/main after a fetch",
                      " ".join(self.system_messages(conversation["id"])))

    def test_the_default_base_stays_the_checkout_head(self):
        self.advance_origin()
        made = self.child("kid")
        self.assertEqual(made.status_code, 201, made.text)  # a person may still cut from HEAD
        conversation = made.json()["conversation"]
        self.assertEqual(self.child_head(conversation), self.local_main())
        self.assertNotIn("cut from", " ".join(self.system_messages(conversation["id"])))

    def test_a_person_may_ask_for_the_upstream_base_too(self):
        self.advance_origin()
        made = self.child("kid", base="upstream")
        self.assertEqual(made.status_code, 201, made.text)
        self.assertEqual(self.child_head(made.json()["conversation"]), self.origin_main())

    def test_no_upstream_refuses_the_upstream_base(self):
        plain = os.path.join(self.directory.name, "plain")
        os.makedirs(plain)
        _git("init", "-q", "-b", "main", cwd=plain)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=plain)
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (plain,))
        made = self.child("kid", headers=self.captain, base="upstream")
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("no upstream to cut from", made.json()["detail"])

    def test_a_stale_branch_never_poses_as_the_requested_base(self):
        # Fable's B2: line/kid survived an earlier purge; the upstream base
        # cannot be honoured on the existing branch, so the birth fails and
        # rolls back instead of seating the child on the old tip.
        self.advance_origin()
        _git("branch", "line/kid", "main", cwd=self.repo)
        made = self.child("kid", headers=self.captain, base="upstream")
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("could not be created", made.json()["detail"])
        self.assertEqual(self.client.get("/api/conversations/root/children").json(), [])
        adopted = self.child("kid")  # default base keeps its behaviour (a person may cut stale)
        self.assertEqual(adopted.status_code, 201, adopted.text)

    def test_an_unknown_base_value_is_rejected(self):
        made = self.child("kid", base="origin/HEAD")
        self.assertEqual(made.status_code, 422, made.text)

    def test_a_failed_upstream_placement_fails_the_create_rolled_back(self):
        self.advance_origin()
        original = line_worktree_module._git

        def add_fails(*args, cwd):
            if args[:2] == ("worktree", "add"):
                return subprocess.CompletedProcess(args, 128, "", "fatal: cannot create")
            return original(*args, cwd=cwd)

        with patch.object(line_worktree_module, "_git", side_effect=add_fails):
            made = self.child("kid", headers=self.captain, base="upstream")
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("could not be created", made.json()["detail"])
        # no orphan line seated in the stale checkout the feature exists to avoid
        self.assertEqual(self.client.get("/api/conversations/root/children").json(), [])

    def test_an_unfetchable_upstream_is_a_409(self):
        self.advance_origin()
        original = checkout_health_module._git

        def fetch_fails(cwd, *args, timeout=5):
            if args[:1] == ("fetch",):
                return subprocess.CompletedProcess(args, 128, "", "fatal: could not read")
            return original(cwd, *args, timeout=timeout)

        with patch.object(checkout_health_module, "_git", side_effect=fetch_fails):
            made = self.child("kid", headers=self.captain, base="upstream")
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("could not be fetched", made.json()["detail"])
        self.assertEqual(self.client.get("/api/conversations/root/children").json(), [])

    def test_the_upstream_base_rides_the_birth_notice_of_placed_records(self):
        placed = place_child(self.db, "root",
                             self.db.create_conversation("kid", "kid")["id"])
        self.assertNotIn("cut from", placed.get("base") or "")
        self.assertIsNone(placed["base"])


if __name__ == "__main__":
    unittest.main()
