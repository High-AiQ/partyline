"""One line, one branch: attachments outside the line worktree warn, machines never stray."""

import os
import subprocess
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_worktree import describe, place_child
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class BranchOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.repo)
        self.elsewhere = os.path.join(self.directory.name, "elsewhere")
        os.makedirs(self.elsewhere)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))

        async def fake_start(att, **kwargs):
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

    def attach(self, name, headers=None, cwd="", conv_id=None):
        return self.client.post(
            f"/api/conversations/{conv_id or self.kid['id']}/attachments",
            json={"name": name, "adapter": "raw", "command": "sh", "cwd": cwd},
            headers=headers or self.human,
        )

    def system_messages(self, conv_id):
        rows = self.db._exec(
            "SELECT body FROM messages WHERE conv_id=? AND sender_type='system' ORDER BY id",
            (conv_id,),
        ).fetchall()
        return [row["body"] for row in rows]

    def test_a_person_attach_outside_the_worktree_warns_on_the_line(self):
        made = self.attach("stray", cwd=self.elsewhere)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["cwd"], self.elsewhere)  # a person may still choose
        warning = " ".join(self.system_messages(self.kid["id"]))
        self.assertIn("⚠ attached outside this line's worktree", warning)
        self.assertIn(self.elsewhere, warning)
        self.assertIn("line/kid", warning)  # the one branch the parent accepts

    def test_a_person_attach_inside_the_worktree_never_warns(self):
        made = self.attach("local", cwd=self.worktree)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertNotIn("⚠ attached outside", " ".join(self.system_messages(self.kid["id"])))

    def test_a_machine_attach_is_placed_where_the_line_works(self):
        self.db.add_attachment("kid-lead", self.kid["id"], "sol", "fake", ["fake"], self.elsewhere)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='kid-lead'")
        captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "kid-lead")}
        made = self.attach("worker", headers=captain, cwd=self.elsewhere)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["cwd"], self.worktree)  # machines cannot choose
        self.assertNotIn("⚠ attached outside", " ".join(self.system_messages(self.kid["id"])))

    def test_a_line_without_a_placed_worktree_warns_generically(self):
        made = self.attach("rover", cwd=self.elsewhere, conv_id="root")
        self.assertEqual(made.status_code, 200, made.text)
        warning = " ".join(self.system_messages("root"))
        self.assertIn("⚠ attached outside this line's working directory", warning)
        self.assertIn("do not land on the line's branch", warning)

    def test_the_birth_notice_says_the_line_owns_exactly_one_branch(self):
        placed = place_child(self.db, "root", self.db.create_conversation("kid2", "kid2")["id"])
        text = describe(placed)
        self.assertIn("owns exactly one branch", text)
        self.assertIn("the branch is what the parent accepts", text)


if __name__ == "__main__":
    unittest.main()
