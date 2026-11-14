"""A machine sees its own line and descendants on the list routes, never an ancestor or a name clash."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.hierarchy import set_parent
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


class Adapter:
    def __init__(self, att):
        self.att = att


class MachineVisibilityRoutesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("p", "Parent")
        self.db.create_conversation("c", "Child")
        # An unrelated line whose display name equals the ancestor's.
        self.db.create_conversation("u", "Parent")
        set_parent(self.db, "c", "p")
        self.db._exec("UPDATE conversations SET goal=? WHERE id=?", ("PRIVATE PARENT GOAL", "p"))
        self.add_live("c-att", "c", "child-worker")
        self.add_live("u-att", "u", "stranger")

        app = FastAPI()
        install_auth_guard(app, self.db)
        media = MediaStore(self.db, self.directory.name + "/media")

        async def fake_start(att, **kwargs):
            return {"id": att["id"], "name": att["name"], "status": att["status"]}

        register_conversation_routes(app, self.runtime, media, None, {}, {}, fake_start)
        app.get("/api/running")(server.running)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

        self._runtime = server.runtime
        server.runtime = self.runtime
        self.addCleanup(setattr, server, "runtime", self._runtime)

        self.child = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "c-att")}
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}

    def add_live(self, ident, conv_id, name):
        owner = f"owner-{ident}"
        self.db.add_attachment(ident, conv_id, name, "raw", ["sh"], self.directory.name, owner)
        self.db.set_attachment_status(ident, "running", owner)
        self.runtime.live[ident] = Adapter(
            {"id": ident, "name": name, "adapter": "raw", "runtime_owner": owner})

    def test_machine_listing_omits_an_ancestor_and_its_goal(self):
        response = self.client.get("/api/conversations", headers=self.child)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("PRIVATE PARENT GOAL", response.text)
        self.assertEqual({row["id"] for row in response.json()}, {"c"})
        self.assertEqual(self.client.get("/api/conversations/p", headers=self.child).status_code, 403)

    def test_people_still_list_every_line(self):
        listed = {row["id"] for row in self.client.get("/api/conversations", headers=self.human).json()}
        self.assertTrue({"p", "c", "u"} <= listed)

    def test_running_never_names_an_unrelated_process_that_shares_an_ancestor_name(self):
        response = self.client.get("/api/running", headers=self.child)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([process["name"] for process in response.json()], ["child-worker"])
        self.assertNotIn("stranger", response.text)

    def test_people_see_every_running_process(self):
        names = {process["name"] for process in self.client.get("/api/running", headers=self.human).json()}
        self.assertEqual(names, {"child-worker", "stranger"})
