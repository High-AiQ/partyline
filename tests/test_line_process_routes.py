import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.hierarchy import set_parent
from partyline.line_process_routes import register_line_process_routes
from partyline.runtime import ChatRuntime


class Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class Adapter:
    def __init__(self, att, status):
        self.att = att
        self.status = status
        self.stopped = False

    async def stop(self):
        self.stopped = True
        await self.status("detached")


class CloseLineProcessesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_line_process_routes(app, self.runtime)
        self.client = TestClient(app)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        token = auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])
        self.client.headers["Authorization"] = f"Bearer {token}"

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def add_live(self, ident: str, name: str, conv_id: str = "line") -> Adapter:
        owner = f"owner-{ident}"
        self.db.add_attachment(
            ident, conv_id, name, "raw", ["sh"], self.directory.name, owner
        )
        self.db.set_attachment_status(ident, "running", owner)
        adapter = Adapter(
            {"runtime_owner": owner}, self.runtime.status_callback(ident, conv_id, owner)
        )
        self.runtime.live[ident] = adapter
        return adapter

    def test_close_detaches_every_live_process_and_keeps_the_line(self):
        first = self.add_live("one", "sol")
        second = self.add_live("two", "fable")
        self.db.add_attachment(
            "old", "line", "old", "raw", ["sh"], self.directory.name, "owner-old"
        )
        self.db.set_attachment_status("old", "detached", "owner-old")
        line_socket = Socket()
        other_socket = Socket()
        self.runtime.sockets = {"line": {line_socket}, "other": {other_socket}}

        self.assertEqual(self.db.list_conversations()[1]["live_count"], 2)
        response = self.client.post("/api/conversations/line/attachments/close")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "stopped": ["sol", "fable"]})
        self.assertTrue(first.stopped and second.stopped)
        self.assertEqual(self.db.get_conversation("line")["live_count"], 0)
        self.assertIsNotNone(self.db.get_conversation("line"))
        self.assertEqual(
            [message["body"] for message in self.db.list_messages("line")],
            ["@sol detached", "@fable detached"],
        )
        self.assertTrue(any(event["type"] == "attachment" for event in line_socket.sent))
        global_events = [event for event in other_socket.sent if event["type"] == "line_live"]
        self.assertEqual(global_events[-1], {
            "type": "line_live", "conversation_id": "line", "live_count": 0,
        })

    def test_empty_missing_and_archived_lines_have_explicit_results(self):
        empty = self.client.post("/api/conversations/line/attachments/close")
        self.assertEqual(empty.json(), {"ok": True, "stopped": []})
        self.assertEqual(
            self.client.post("/api/conversations/missing/attachments/close").status_code, 404
        )
        self.db.archive_conversation("line")
        archived = self.client.post("/api/conversations/line/attachments/close")
        self.assertEqual(archived.status_code, 409)

    def test_close_detaches_processes_across_sublines(self):
        parent_adapter = self.add_live("one", "sol", conv_id="line")
        self.db.create_conversation("sub", "Subline")
        set_parent(self.db, "sub", "line")
        child_adapter = self.add_live("two", "fable", conv_id="sub")
        self.db.create_conversation("sub2", "Grandchild")
        set_parent(self.db, "sub2", "sub")
        grandchild_adapter = self.add_live("three", "echo", conv_id="sub2")

        response = self.client.post("/api/conversations/line/attachments/close")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "stopped": ["sol", "fable", "echo"]},
        )
        self.assertTrue(parent_adapter.stopped)
        self.assertTrue(child_adapter.stopped)
        self.assertTrue(grandchild_adapter.stopped)
        self.assertEqual(self.db.get_conversation("line")["live_count"], 0)
        self.assertEqual(self.db.get_conversation("sub")["live_count"], 0)
        self.assertEqual(self.db.get_conversation("sub2")["live_count"], 0)
        self.assertEqual(
            [message["body"] for message in self.db.list_messages("line")],
            ["@sol detached"],
        )
        self.assertEqual(
            [message["body"] for message in self.db.list_messages("sub")],
            ["@fable detached"],
        )
        self.assertEqual(
            [message["body"] for message in self.db.list_messages("sub2")],
            ["@echo detached"],
        )

