import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.agent_connection import connection_directory, provision_connection
from partyline.auth_store import rotate_api_token
from partyline.db import Db
from partyline.hierarchy import set_parent
from partyline.hierarchy_routes import hierarchy_router
from partyline.machine_scope import deny_unless_attachment
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
        app.include_router(hierarchy_router(self.runtime))

        @app.delete("/api/attachments/{att_id}")
        async def detach(request: Request, att_id: str):
            return await close_attachment(self.runtime, att_id)

        @app.post("/api/attachments/{att_id}/resume")
        async def resume(request: Request, att_id: str):
            deny_unless_attachment(self.db, request.state.principal, att_id, "attach")
            owner = f"resumed-{att_id}"
            token = rotate_api_token(self.db, att_id)
            self.db._exec(
                "UPDATE attachments SET status='running', runtime_owner=? WHERE id=?",
                (owner, att_id),
            )
            resumed = self.db.get_attachment(att_id)
            resumed["runtime_owner"] = owner
            resumed["api_token"] = token
            with patch.dict(os.environ, {"PARTYLINE_TMP_BASE": self.directory.name}):
                provision_connection(self.db.path, resumed)
            return {"ok": True}

        self.client = TestClient(app)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        token = auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])
        self.human_token = token
        self.client.headers["Authorization"] = f"Bearer {token}"

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def add_live(self, ident: str, name: str, conv_id: str = "line") -> Adapter:
        owner = f"owner-{ident}"
        self.db.add_attachment(
            ident, conv_id, name, "raw", ["sh"], self.directory.name, owner,
            counts_toward_total=True
        )
        self.db.set_attachment_status(ident, "running", owner)
        adapter = Adapter(
            {"runtime_owner": owner}, self.runtime.status_callback(ident, conv_id, owner)
        )
        self.runtime.live[ident] = adapter
        attachment = self.db.get_attachment(ident)
        attachment["api_token"] = auth_store.ensure_api_token(self.db, ident)
        with patch.dict(os.environ, {"PARTYLINE_TMP_BASE": self.directory.name}):
            provision_connection(self.db.path, attachment)
        return adapter

    def machine_helper(self, ident: str) -> MCPServer:
        path = connection_directory(self.db.path) / f"{ident}.json"
        with path.open() as stream:
            connection = json.load(stream)

        class RouteClient:
            def __init__(inner_self):
                inner_self.connection = connection
                inner_self.capability_calls = 0

            def capabilities(inner_self):
                inner_self.capability_calls += 1
                response = self.client.get(
                    "/api/capabilities",
                    headers={"Authorization": "Bearer " + inner_self.connection["token"]},
                )
                if response.status_code == 401:
                    raise ApiError(f"Partyline HTTP 401: {response.json()['detail']}")
                return response.json()

        live_client = RouteClient()
        helper = MCPServer(live_client, output=io.StringIO())
        helper.live_client = live_client
        return helper

    @staticmethod
    def rpc_result(helper: MCPServer, ident: int) -> dict:
        return next(
            row for row in (json.loads(line) for line in helper.output.getvalue().splitlines())
            if row.get("id") == ident
        )

    def helper_tools_list(self, helper: MCPServer, ident: int) -> dict:
        helper.handle({"jsonrpc": "2.0", "id": ident, "method": "tools/list"})
        return self.rpc_result(helper, ident)

    def assert_h1_succeeds_before_stop(self, helper: MCPServer):
        result = self.helper_tools_list(helper, 1)
        self.assertIn("tools", result["result"])
        self.assertFalse(result["result"].get("isError", False))

    def assert_h1_is_rejected_after_stop(self, helper: MCPServer, ident: int):
        result = self.helper_tools_list(helper, ident)
        self.assertEqual(result["error"]["code"], -32001)
        self.assertIn("Partyline HTTP 401", result["error"]["message"])
        self.assertTrue(helper._revoked)

    def assert_h1_stays_revoked_after_resume(self, helper: MCPServer):
        before = helper.live_client.capability_calls
        result = self.helper_tools_list(helper, 3)
        self.assertEqual(result["error"]["code"], -32001)
        self.assertIn("credential is no longer valid", result["error"]["message"])
        self.assertEqual(helper.live_client.capability_calls, before)

    def assert_h2_succeeds_after_resume(self, ident: str, old_token: str):
        helper = self.machine_helper(ident)
        self.assertNotEqual(helper.live_client.connection["token"], old_token)
        result = self.helper_tools_list(helper, 1)
        self.assertIn("tools", result["result"])
        self.assertFalse(result["result"].get("isError", False))

    def revoke_and_resume(self, ident: str, helper: MCPServer, stop_response):
        self.assertEqual(stop_response.status_code, 200)
        before_messages = self.db.list_messages("line")
        self.assert_h1_is_rejected_after_stop(helper, 2)
        self.assertEqual(helper.live_client.capability_calls, 2)
        calls_after_reject = helper.live_client.capability_calls
        self.assertEqual(calls_after_reject, 2)
        self.assertNotIn("notifications/tools/list_changed", helper.output.getvalue())
        self.assertEqual(self.client.post(
            f"/api/attachments/{ident}/resume",
            headers={"Authorization": "Bearer " + self.human_token},
        ).status_code, 200)
        old_token = helper.live_client.connection["token"]
        self.assert_h1_stays_revoked_after_resume(helper)
        self.assertEqual(helper.live_client.capability_calls, calls_after_reject)
        self.assertEqual(self.db.list_messages("line"), before_messages)
        self.assert_h2_succeeds_after_resume(ident, old_token)

    def test_single_detach_h1_is_revoked_across_resume_and_h2_uses_rotated_token(self):
        self.add_live("one", "sol")
        helper = self.machine_helper("one")
        self.assert_h1_succeeds_before_stop(helper)
        helper.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        response = self.client.delete(
            "/api/attachments/one", headers={"Authorization": "Bearer " + self.human_token}
        )
        self.revoke_and_resume("one", helper, response)

    def test_bulk_close_revokes_each_h1_across_resume_and_h2_uses_rotated_token(self):
        self.add_live("one", "sol")
        self.add_live("two", "fable")
        helpers = {ident: self.machine_helper(ident)
                   for ident in ("one", "two")}
        for helper in helpers.values():
            self.assert_h1_succeeds_before_stop(helper)
            helper.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        response = self.client.post("/api/conversations/line/attachments/close")
        self.assertEqual(response.status_code, 200)
        for ident, helper in helpers.items():
            with self.subTest(attachment=ident):
                self.revoke_and_resume(ident, helper, response)

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

