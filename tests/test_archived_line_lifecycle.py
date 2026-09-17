"""Lifecycle coverage for lines that have been archived."""

import asyncio
import tempfile
import unittest


from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


class FakeWebSocket:
    def __init__(self, payload, token=""):
        self.payload = payload
        self.sent = []
        self.headers = {}
        self.query_params = {"token": token} if token else {}

    async def accept(self):
        pass

    async def close(self, code, reason=""):
        self.closed = (code, reason)

    async def receive_json(self):
        if self.payload is None:
            raise WebSocketDisconnect()
        payload, self.payload = self.payload, None
        return payload

    async def send_json(self, event):
        self.sent.append(event)


class ArchivedLineLifecycleTest(unittest.TestCase):
    def test_websocket_message_to_archived_line_is_rejected_and_not_saved(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database:
            original_runtime = server.runtime
            try:
                server.runtime = ChatRuntime(Db(database.name))
                conversation = server.runtime.db.create_conversation("archived", "Old line")
                server.runtime.db.archive_conversation(conversation["id"])
                user = auth_store.create_user(
                    server.runtime.db, "terra@example.com", "terra",
                    auth_tokens.hash_password("hunter2222"))
                token = auth_tokens.create_access_token(
                    auth_tokens.signing_secret(server.runtime.db), user["id"])
                socket = FakeWebSocket({"body": "should not persist"}, token=token)

                asyncio.run(server.ws_endpoint(socket, conversation["id"]))

                self.assertEqual(socket.sent, [{
                    "type": "error",
                    "conversation_id": conversation["id"],
                    "message": "this line is archived — restore it to talk here",
                }])
                self.assertEqual(server.runtime.db.list_messages(conversation["id"]), [])
            finally:
                server.runtime.db.close()
                server.runtime = original_runtime


class PurgeAllArchivedTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(self.directory.name + "/test.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.media = MediaStore(self.db, self.directory.name + "/media")
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_conversation_routes(
            app, self.runtime, self.media,
            None, {}, {}, None,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(setattr, server, "runtime", server.runtime)
        self.addCleanup(setattr, server, "media", server.media)
        server.runtime = self.runtime
        server.media = self.media

        user = auth_store.create_user(
            self.db, "terra@example.com", "terra",
            auth_tokens.hash_password("hunter2222"),
        )
        self.human = {
            "Authorization": "Bearer "
            + auth_tokens.create_access_token(
                auth_tokens.signing_secret(self.db), user["id"]
            )
        }
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("agent-att", "root", "agent", "fake", ["fake"], self.directory.name)
        self.machine = {
            "Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "agent-att")
        }

    def test_human_only_403(self):
        res = self.client.delete("/api/conversations/archived", headers=self.machine)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "only a human can purge all archived lines")

    def test_empty_set(self):
        res = self.client.delete("/api/conversations/archived", headers=self.human)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"purged": [], "skipped": []})

    def test_purges_archived_children_of_live_parent(self):
        for index in range(10):
            child_id = f"kid-{index}"
            self.db.create_conversation(child_id, f"Kid {index}")
            self.db._exec(
                "UPDATE conversations SET parent_id='root' WHERE id=?", (child_id,)
            )
            self.db.archive_conversation(child_id)

        res = self.client.delete("/api/conversations/archived", headers=self.human)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(set(data["purged"]), {f"kid-{index}" for index in range(10)})
        self.assertEqual(data["skipped"], [])
        for index in range(10):
            self.assertIsNone(self.db.get_conversation(f"kid-{index}"))

    def test_ordering(self):
        self.db.create_conversation("tree_root", "Tree Root")
        self.db.create_conversation("tree_child", "Tree Child")
        self.db._exec("UPDATE conversations SET parent_id='tree_root' WHERE id='tree_child'")
        self.db.create_conversation("tree_grandchild", "Tree Grandchild")
        self.db._exec("UPDATE conversations SET parent_id='tree_child' WHERE id='tree_grandchild'")

        self.db.archive_conversation("tree_grandchild")
        self.db.archive_conversation("tree_child")
        self.db.archive_conversation("tree_root")

        res = self.client.delete("/api/conversations/archived", headers=self.human)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["skipped"], [])
        self.assertEqual(data["purged"], ["tree_grandchild", "tree_child", "tree_root"])
        self.assertIsNone(self.db.get_conversation("tree_grandchild"))
        self.assertIsNone(self.db.get_conversation("tree_child"))
        self.assertIsNone(self.db.get_conversation("tree_root"))

    def test_purges_archived_descendants_when_ancestor_unarchived(self):
        # root is active (not archived)
        # kid is archived, parent = root
        # grandkid is archived, parent = kid
        self.db.create_conversation("kid", "Kid")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='kid'")
        self.db.create_conversation("grandkid", "Grandkid")
        self.db._exec("UPDATE conversations SET parent_id='kid' WHERE id='grandkid'")
        self.db.archive_conversation("grandkid")
        self.db.archive_conversation("kid")

        res = self.client.delete("/api/conversations/archived", headers=self.human)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["purged"], ["grandkid", "kid"])
        self.assertEqual(data["skipped"], [])
        self.assertIsNone(self.db.get_conversation("kid"))
        self.assertIsNone(self.db.get_conversation("grandkid"))

    def test_archived_parent_with_restored_child(self):
        self.db.create_conversation("parent_line", "Parent")
        self.db.create_conversation("child_line", "Child")
        self.db._exec("UPDATE conversations SET parent_id='parent_line' WHERE id='child_line'")
        self.db.archive_conversation("child_line")
        self.db.archive_conversation("parent_line")
        self.db.restore_conversation("child_line")

        self.db.create_conversation("unrelated", "Unrelated")
        self.db.archive_conversation("unrelated")

        res = self.client.delete("/api/conversations/archived", headers=self.human)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["purged"], ["unrelated"])
        self.assertEqual(
            data["skipped"],
            [{"id": "parent_line", "reason": "line has a child that is not archived"}],
        )
        parent = self.db.get_conversation("parent_line")
        self.assertIsNotNone(parent)
        self.assertIsNotNone(parent["archived_at"])
        child = self.db.get_conversation("child_line")
        self.assertIsNotNone(child)
        self.assertIsNone(child["archived_at"])
        self.assertIsNone(self.db.get_conversation("unrelated"))

    def test_skip_propagates_to_archived_ancestor(self):
        self.db.create_conversation("gp", "Grandparent")
        self.db.create_conversation("p", "Parent")
        self.db._exec("UPDATE conversations SET parent_id='gp' WHERE id='p'")
        self.db.create_conversation("c", "Child")
        self.db._exec("UPDATE conversations SET parent_id='p' WHERE id='c'")

        self.db.archive_conversation("c")
        self.db.archive_conversation("p")
        self.db.archive_conversation("gp")
        self.db.restore_conversation("c")

        res = self.client.delete("/api/conversations/archived", headers=self.human)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["purged"], [])
        skipped_map = {item["id"]: item["reason"] for item in data["skipped"]}
        self.assertEqual(skipped_map.get("p"), "line has a child that is not archived")
        self.assertEqual(skipped_map.get("gp"), "line has a child that is not archived")
        self.assertIsNotNone(self.db.get_conversation("gp"))
        self.assertIsNotNone(self.db.get_conversation("p"))
        child = self.db.get_conversation("c")
        self.assertIsNotNone(child)
        self.assertIsNone(child["archived_at"])

