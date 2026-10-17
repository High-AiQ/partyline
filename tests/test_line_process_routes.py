import io
import json
import tempfile
import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.hierarchy import set_parent
from partyline.line_process_routes import close_attachment, register_line_process_routes
from partyline.runtime import ChatRuntime
from partyline.mcp.client import ApiError
from partyline.mcp.server import MCPServer


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

        @app.get("/api/probe")
        async def probe():
            return {"ok": True}

        @app.delete("/api/attachments/{att_id}")
        async def detach(request: Request, att_id: str):
            return await close_attachment(self.runtime, att_id)

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

    def machine_helper(self, token: str) -> MCPServer:
        class LiveClient:
            def capabilities(inner_self):
                response = self.client.get(
                    "/api/probe", headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 401:
                    raise ApiError("Partyline HTTP 401: authentication required")
                return {"kind": "machine", "role": "worker", "conv_id": "line",
                        "attachment_id": "one", "is_lead": False, "actions": []}

            connection = {"api": "http://partyline", "handle": "worker"}

        return MCPServer(LiveClient(), output=io.StringIO())

    def assert_helper_revoked(self, token: str):
        helper = self.machine_helper(token)
        helper.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "context", "arguments": {}},
        })
        result = json.loads(helper.output.getvalue())
        self.assertTrue(result["result"]["isError"])
        self.assertIn("Partyline HTTP 401", result["result"]["content"][0]["text"])
        self.assertTrue(helper._revoked)

    def test_single_detach_revokes_helper_on_its_next_call(self):
        self.add_live("one", "sol")
        token = auth_store.ensure_api_token(self.db, "one")
        response = self.client.delete(
            "/api/attachments/one", headers={
                "Authorization": "Bearer " + auth_tokens.create_access_token(
                    auth_tokens.signing_secret(self.db),
                    auth_store.create_user(self.db, "x@example.com", "x", "hash")["id"],
                )
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(
            "/api/probe", headers={"Authorization": f"Bearer {token}"}
        ).status_code, 401)
        self.assert_helper_revoked(token)

    def test_bulk_close_revokes_each_running_helper_on_its_next_call(self):
        self.add_live("one", "sol")
        self.add_live("two", "fable")
        tokens = [auth_store.ensure_api_token(self.db, ident) for ident in ("one", "two")]
        self.client.headers["Authorization"] = "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db),
            auth_store.create_user(self.db, "bulk@example.com", "bulk", "hash")["id"],
        )
        response = self.client.post("/api/conversations/line/attachments/close")
        self.assertEqual(response.status_code, 200)
        for token in tokens:
            with self.subTest(token=token[:6]):
                self.assertEqual(self.client.get(
                    "/api/probe", headers={"Authorization": f"Bearer {token}"}
                ).status_code, 401)
                self.assert_helper_revoked(token)

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

    def test_close_can_leave_sublines_alone(self):
        parent_adapter = self.add_live("one", "sol", conv_id="line")
        self.db.create_conversation("sub", "Subline")
        set_parent(self.db, "sub", "line")
        child_adapter = self.add_live("two", "fable", conv_id="sub")

        response = self.client.post(
            "/api/conversations/line/attachments/close?include_children=false")
        self.assertEqual(response.json(), {"ok": True, "stopped": ["sol"]})
        self.assertTrue(parent_adapter.stopped)
        self.assertFalse(child_adapter.stopped)

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

