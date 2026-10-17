import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from partyline.mcp import client as client_module
from partyline.mcp.client import ApiError, PartylineClient
from partyline.mcp.render import MAX_TEXT, render
from partyline.mcp import server as server_module
from partyline.mcp.server import MCPServer
from partyline.mcp import tools_core
from partyline.mcp import tools_captain


class Response:
    def __init__(self, body=b"{}", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {"Content-Length": str(len(body))}
        self.offset = 0

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, size=-1):
        end = len(self.body) if size < 0 else min(len(self.body), self.offset + size)
        value = self.body[self.offset:end]
        self.offset = end
        return value


class Connection:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.sent = []
        self.request_args = None
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.request_args = (method, path, body)
        self.headers = headers or {}

    def putrequest(self, method, path):
        self.request_args = (method, path, None)

    def putheader(self, key, value):
        self.headers[key] = value

    def endheaders(self):
        pass

    def send(self, body):
        self.sent.append(body)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, actions=("read", "write", "assign", "report", "notify", "read_reports")):
        self.connection = {"api": "http://127.0.0.1:8643", "handle": "worker",
                           "attachment_id": "att-1", "conversation_id": "home"}
        self.home = "home"
        self.state = {"kind": "machine", "role": "lead", "conv_id": "home",
                      "attachment_id": "att-1", "is_lead": True,
                      "parent_id": "parent", "actions": list(actions)}
        self.requests = []
        self.target_state = {**self.state, "conv_id": "child"}
        self.responses = {}
        self.deny_child_post = False

    def capabilities(self, conv_id=None):
        self.requests.append(("CAP", conv_id))
        return self.target_state if conv_id and conv_id != self.home else self.state

    def request(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if self.deny_child_post and method == "POST" and path.endswith("/messages"):
            raise ApiError("Partyline HTTP 403")
        if path.endswith("/children"):
            return [{"id": "child", "name": "child-line"}]
        if method == "GET" and path == "/api/conversations/home":
            return {"conversation": {"id": "home", "name": "main", "topic": "topic"},
                    "messages": [{"body": "ignored"}],
                    "attachments": [{"id": "att-1", "name": "worker", "status": "running",
                                     "is_lead": True, "adapter": "claude", "secret": "omit"}]}
        return self.responses.get((method, path), {"ok": True})

    def upload(self, conv_id, file_path, **kwargs):
        self.requests.append(("UPLOAD", conv_id, file_path, kwargs))
        return {"ok": True}

    def download(self, file_id, variant, destination):
        self.requests.append(("DOWNLOAD", file_id, variant, destination))
        return {"bytes": 1}


class MCPClientTests(unittest.TestCase):
    def client(self, response):
        client = PartylineClient.__new__(PartylineClient)
        client.connection = {"api": "http://127.0.0.1:8643", "token": "secret",
                             "conversation_id": "home", "attachment_id": "att", "handle": "worker"}
        connection = Connection(response)
        client._origin = lambda: connection
        return client, connection

    def test_json_request_uses_scoped_bearer_and_rejects_oversize(self):
        client, conn = self.client(Response(b'{"actions":[]}'))
        self.assertEqual(client.request("GET", "/api/capabilities"), {"actions": []})
        self.assertEqual(conn.headers["Authorization"], "Bearer secret")
        self.assertTrue(conn.closed)
        too_large, _ = self.client(Response(b"12345", headers={"Content-Length": "5"}))
        with patch.object(client_module, "MAX_RESPONSE", 4):
            with self.assertRaisesRegex(ApiError, "MCP limit"):
                too_large.request("GET", "/api/capabilities")

    def test_json_request_surfaces_bounded_http_error(self):
        client, _ = self.client(Response(b'{"detail":"denied"}', 403))
        with self.assertRaisesRegex(ApiError, "HTTP 403: denied"):
            client.request("GET", "/api/capabilities")

    def test_invalid_path_invalid_json_and_body_limit_without_length(self):
        client, _ = self.client(Response(b"{}"))
        with self.assertRaisesRegex(ValueError, "local /api/"):
            client.request("GET", "https://example.invalid/api/x")
        malformed, _ = self.client(Response(b"not json"))
        with self.assertRaisesRegex(ApiError, "invalid JSON"):
            malformed.request("GET", "/api/capabilities")
        oversized, _ = self.client(Response(b"12345", headers={}))
        with patch.object(client_module, "MAX_RESPONSE", 4):
            with self.assertRaisesRegex(ApiError, "MCP limit"):
                oversized.request("GET", "/api/capabilities")

    def test_connection_file_is_loaded_without_exposing_token(self):
        data = {"api": "https://partyline.example", "token": "secret-token",
                "conversation_id": "home", "attachment_id": "att", "handle": "worker"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connection.json"
            path.write_text(json.dumps(data))
            path.chmod(0o600)
            client = PartylineClient(str(path))
        self.assertEqual(client.home, "home")
        self.assertEqual(client.connection["handle"], "worker")
        self.assertNotIn("secret-token", repr(client.connection).replace("'token': 'secret-token'", ""))

    def test_missing_connection_path_and_origin_schemes(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "PARTYLINE_MCP_CONNECTION"):
                PartylineClient()
        client, _ = self.client(Response(b"{}"))
        del client._origin
        def http_factory(host, port, timeout):
            return host, port, timeout

        with patch.object(client_module.http.client, "HTTPConnection", http_factory):
            self.assertEqual(client._origin(), ("127.0.0.1", 8643, 30))
        client.connection["api"] = "https://partyline.example"
        def https_factory(host, port, timeout):
            return host, port, timeout

        with patch.object(client_module.http.client, "HTTPSConnection", https_factory):
            self.assertEqual(client._origin(), ("partyline.example", 443, 30))

    def test_empty_json_body_and_capabilities_non_mapping(self):
        client, conn = self.client(Response(b""))
        self.assertEqual(client.request("POST", "/api/test", {"value": 1}), {})
        self.assertEqual(conn.headers["Content-Length"], str(len(b'{"value": 1}')))
        client.request = lambda *_args: []
        self.assertEqual(client.capabilities(), {})
        self.assertEqual(client.capabilities("line/a"), {})

    def test_error_parser_handles_non_json_and_non_string_detail(self):
        self.assertEqual(str(PartylineClient._error(403, b"not json")), "Partyline HTTP 403")
        self.assertEqual(str(PartylineClient._error(403, b'{"detail":{"why":"no"}}')),
                         "Partyline HTTP 403")

    def test_upload_streams_multipart_and_checks_file_size(self):
        client, conn = self.client(Response(b'{"files":[]}'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_bytes(b"payload")
            result = client.upload("line/a", str(path), client_key="upload-1", title="short")
        self.assertEqual(result, {"files": []})
        self.assertEqual(conn.request_args[0], "POST")
        self.assertIn("/api/conversations/line%2Fa/files", conn.request_args[1])
        self.assertIn(b"payload", b"".join(conn.sent))
        self.assertIn(b"name=\"client_key\"", b"".join(conn.sent))
        self.assertIn(b"upload-1", b"".join(conn.sent))
        self.assertEqual(int(conn.headers["Content-Length"]), sum(map(len, conn.sent)))
        self.assertTrue(conn.closed)

    def test_upload_rejects_oversize_before_connecting(self):
        client = PartylineClient.__new__(PartylineClient)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large"
            path.write_bytes(b"123")
            with patch.object(client_module, "MAX_UPLOAD", 2):
                with self.assertRaisesRegex(ValueError, "no larger"):
                    client.upload("home", str(path), client_key="key")

    def test_upload_requires_idempotency_key(self):
        client = PartylineClient.__new__(PartylineClient)
        with self.assertRaisesRegex(ValueError, "stable client_key"):
            client.upload("home", "missing", client_key="")

    def test_upload_metadata_limits_and_http_failure(self):
        client = PartylineClient.__new__(PartylineClient)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample"
            path.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "metadata"):
                client.upload("home", str(path), client_key="key", title="x" * 201)
        client, conn = self.client(Response(b'{"detail":"no write"}', 403))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample"
            path.write_bytes(b"x")
            with self.assertRaisesRegex(ApiError, "HTTP 403: no write"):
                client.upload("home", str(path), client_key="key")
        self.assertTrue(conn.closed)

    def test_upload_rejects_directory_and_response_bound_or_invalid_json(self):
        client = PartylineClient.__new__(PartylineClient)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "regular file"):
                client.upload("home", directory, client_key="key")
            path = Path(directory) / "sample.unknown"
            path.write_bytes(b"x")
            success, conn = self.client(Response(b"bad"))
            with self.assertRaises(json.JSONDecodeError):
                success.upload("home", str(path), client_key="key",
                               description="d", body="caption")
            self.assertTrue(conn.closed)
            oversize, _ = self.client(Response(b"123"))
            with patch.object(client_module, "MAX_RESPONSE", 2):
                with self.assertRaisesRegex(ApiError, "response exceeds"):
                    oversize.upload("home", str(path), client_key="key")

    def test_upload_detects_file_shrink_while_streaming(self):
        client, conn = self.client(Response(b"{}"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample"
            path.write_bytes(b"content")
            original_send = conn.send
            changed = False

            def send_and_shrink(data):
                nonlocal changed
                original_send(data)
                if not changed:
                    path.write_bytes(b"")
                    changed = True

            conn.send = send_and_shrink
            with self.assertRaisesRegex(ValueError, "file changed"):
                client.upload("home", str(path), client_key="key")
        self.assertTrue(conn.closed)

    def test_upload_detects_file_changed_during_stream(self):
        client, conn = self.client(Response(b"{}"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample"
            path.write_bytes(b"x")
            original_send = conn.send
            appended = False

            def send_and_grow(data):
                nonlocal appended
                original_send(data)
                if not appended:
                    with path.open("ab") as stream:
                        stream.write(b"more")
                    appended = True

            conn.send = send_and_grow
            with self.assertRaisesRegex(ValueError, "file changed"):
                client.upload("home", str(path), client_key="key")
        self.assertTrue(conn.closed)

    def test_download_streams_private_file_and_removes_partial_oversize(self):
        client, conn = self.client(Response(b"bytes", headers={"Content-Length": "5",
                                                                  "Content-Type": "text/plain"}))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.txt"
            result = client.download("file-1", "slim", str(path))
            self.assertEqual(path.read_bytes(), b"bytes")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(result["bytes"], 5)
        self.assertTrue(conn.closed)
        too_large, _ = self.client(Response(b"bytes", headers={"Content-Length": "5"}))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial"
            with patch.object(client_module, "MAX_DOWNLOAD", 3):
                with self.assertRaisesRegex(ApiError, "download exceeds"):
                    too_large.download("file-1", "original", str(path))
            self.assertFalse(path.exists())

    def test_download_rejects_variant_existing_target_and_http_error(self):
        client = PartylineClient.__new__(PartylineClient)
        with self.assertRaisesRegex(ValueError, "variant"):
            client.download("f", "bad", "out")
        client, _ = self.client(Response(b"ok"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out"
            path.write_text("existing")
            with self.assertRaises(FileExistsError):
                client.download("f", "original", str(path))
            self.assertEqual(path.read_text(), "existing")
        denied, conn = self.client(Response(b'{"detail":"no access"}', 403))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ApiError, "HTTP 403"):
                denied.download("f", "original", str(Path(directory) / "out"))
        self.assertTrue(conn.closed)

    def test_download_without_length_uses_content_type_fallback(self):
        client, _ = self.client(Response(b"x", headers={"Content-Type": ""}))
        with tempfile.TemporaryDirectory() as directory:
            result = client.download("f", "original", str(Path(directory) / "out"))
        self.assertEqual(result["content_type"], "application/octet-stream")


class CoreToolTests(unittest.TestCase):
    def test_live_capability_list_and_stable_core_names(self):
        worker = tools_core.tool_list({"actions": ["read", "write"]})
        captain = tools_core.tool_list({"actions": ["read", "write", "assign", "read_reports"]})
        names = {item["name"] for item in worker}
        self.assertIn("read_messages", names)
        self.assertNotIn("reports", names)
        self.assertIn("reports", {item["name"] for item in captain})
        self.assertNotIn("captain", {item["name"] for item in captain})
        empty = {item["name"] for item in tools_core.tool_list({"actions": []})}
        self.assertEqual(empty, {"whoami", "guide"})

    def test_post_message_refuses_home_and_rechecks_target_then_uses_key(self):
        client = FakeClient()
        with self.assertRaisesRegex(ValueError, "other than your own"):
            tools_core.call(client, "post_message", {
                "conv_id": "home", "body": "hello", "client_key": "k1"}, client.state)
        tools_core.call(client, "post_message", {
            "conv_id": "child", "body": "hello", "client_key": "stable"}, client.state)
        self.assertIn(("CAP", "child"), client.requests)
        self.assertIn(("POST", "/api/conversations/child/messages",
                       {"body": "hello", "client_key": "stable"}), client.requests)
        client.target_state = {**client.target_state, "actions": ["read"]}
        client.deny_child_post = True
        with self.assertRaisesRegex(ApiError, "HTTP 403"):
            tools_core.call(client, "post_message", {
                "conv_id": "child", "body": "hello", "client_key": "stable"}, client.state)
        with self.assertRaisesRegex(ValueError, "body and a stable"):
            tools_core.call(FakeClient(), "post_message", {
                "conv_id": "child", "body": "", "client_key": "key"}, FakeClient().state)
        with self.assertRaisesRegex(ValueError, "capped at 64"):
            tools_core.call(FakeClient(), "post_message", {
                "conv_id": "child", "body": "hello", "client_key": "x" * 65}, FakeClient().state)

    def test_whoami_returns_only_selected_member_fields(self):
        client = FakeClient()
        result = tools_core.call(client, "whoami", {}, client.state)
        self.assertEqual(result["identity"], "worker")
        self.assertEqual(result["parent_id"], "parent")
        self.assertEqual(result["children"], [{"id": "child", "name": "child-line"}])
        self.assertNotIn("secret", result["members"][0])
        self.assertNotIn("messages", result)

    def test_notes_own_attachment_write_and_captain_only_tree_write(self):
        client = FakeClient()
        tools_core.call(client, "notes", {"operation": "set", "scope": "attachment",
                                            "notes": "checkpoint"}, client.state)
        self.assertEqual(client.requests[-1][0:2], (
            "PUT", "/api/conversations/home/notes?scope=attachment&attachment_id=att-1"))
        state = {**client.state, "actions": ["read"]}
        with self.assertRaisesRegex(ApiError, "only a captain"):
            tools_core.call(client, "notes", {"operation": "set", "scope": "tree",
                                                "notes": "no"}, state)
        tools_core.call(client, "notes", {"operation": "get", "scope": "line"}, client.state)
        tools_core.call(client, "notes", {"operation": "set", "scope": "tree",
                                            "notes": "tree"}, client.state)
        with self.assertRaisesRegex(ValueError, "valid operation"):
            tools_core.call(client, "notes", {"operation": "what", "scope": "line"}, client.state)
        with self.assertRaisesRegex(ValueError, "4000"):
            tools_core.call(client, "notes", {"operation": "set", "scope": "attachment",
                                                "notes": "x" * 4001}, client.state)

    def test_goal_and_report_operations_are_live_gated(self):
        client = FakeClient()
        tools_core.call(client, "goal", {"operation": "set", "goal": "ship"}, client.state)
        self.assertEqual(client.requests[-1][0:2], ("PUT", "/api/conversations/home/goal"))
        tools_core.call(client, "goal", {"operation": "get"}, client.state)
        self.assertEqual(tools_core.call(client, "goal", {"operation": "get"}, client.state),
                         {"id": "home", "name": "main", "topic": "topic", "goal": None})
        tools_core.call(client, "reports", {"operation": "list"}, client.state)
        tools_core.call(client, "reports", {"operation": "post", "body": "status"}, client.state)
        tools_core.call(client, "reports", {"operation": "post", "body": "urgent",
                                              "notify": True}, client.state)
        state = {**client.state, "actions": ["read"]}
        with self.assertRaisesRegex(ApiError, "cannot set"):
            tools_core.call(client, "goal", {"operation": "set", "goal": "ship"}, state)
        with self.assertRaisesRegex(ValueError, "3000"):
            tools_core.call(client, "goal", {"operation": "set", "goal": "x" * 3001}, client.state)
        with self.assertRaisesRegex(ApiError, "cannot read"):
            tools_core.call(client, "reports", {"operation": "list"}, state)
        with self.assertRaisesRegex(ValueError, "get or set"):
            tools_core.call(client, "goal", {"operation": "unset"}, client.state)
        with self.assertRaisesRegex(ValueError, "list or post"):
            tools_core.call(client, "reports", {"operation": "delete"}, client.state)
        with self.assertRaisesRegex(ValueError, "body is required"):
            tools_core.call(client, "reports", {"operation": "post"}, client.state)
        with self.assertRaisesRegex(ApiError, "cannot post"):
            tools_core.call(client, "reports", {"operation": "post", "body": "urgent",
                                                  "notify": True}, state)

    def test_guide_messages_reactions_and_media_use_fixed_routes(self):
        client = FakeClient()
        tools_core.call(client, "guide", {}, client.state)
        with self.assertRaisesRegex(ValueError, "category is required"):
            tools_core.call(client, "guide", {"topic": "mcp"}, client.state)
        tools_core.call(client, "guide", {"category": "captains", "topic": "review"}, client.state)
        tools_core.call(client, "read_messages", {"conv_id": "child", "after_id": 3,
                                                   "limit": 100}, client.state)
        self.assertIn(("CAP", "child"), client.requests)
        self.assertIn("limit=50&after_id=3", client.requests[-1][1])
        tools_core.call(client, "read_messages", {"around_id": 5}, client.state)
        self.assertIn("/messages/around?message_id=5", client.requests[-1][1])
        tools_core.call(client, "react", {"message_id": 9, "emoji": "✅"}, client.state)
        self.assertEqual(client.requests[-1][0], "POST")
        tools_core.call(client, "react", {"message_id": 9, "emoji": "✅", "remove": True}, client.state)
        self.assertEqual(client.requests[-1][0], "DELETE")
        tools_core.call(client, "get_media", {"file_id": "file", "variant": "slim",
                                                "destination": "out.png"}, client.state)
        tools_core.call(client, "upload_file", {
            "conv_id": "child", "path": "in.txt", "client_key": "file-key"}, client.state)
        self.assertIn(("UPLOAD", "child", "in.txt", {
            "title": "", "description": "", "body": "", "client_key": "file-key"}),
            client.requests)


class RenderAndServerTests(unittest.TestCase):
    def test_render_relativizes_media_links_and_caps_output(self):
        text = render({"url": "http://127.0.0.1:8643/api/media/id/slim", "body": "x"},
                      "http://127.0.0.1:8643")
        self.assertIn("/api/media/id/slim", text)
        self.assertNotIn("127.0.0.1", text)
        large = render("x" * MAX_TEXT, "http://127.0.0.1:8643")
        self.assertLessEqual(len(large), MAX_TEXT)
        self.assertIn("truncated", large)

    def test_jsonrpc_list_call_revocation_and_eof(self):
        client = FakeClient(actions=("read", "write"))
        output = io.StringIO()
        server = MCPServer(client, output)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listing = json.loads(output.getvalue().splitlines()[1])
        self.assertIn("read_messages", [tool["name"] for tool in listing["result"]["tools"]])
        server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "post_message", "arguments": {
                           "conv_id": "home", "body": "dup", "client_key": "k"}}})
        called = json.loads(output.getvalue().splitlines()[2])
        self.assertTrue(called["result"]["isError"])
        server._stop.set()
        server.run(io.StringIO())
        self.assertTrue(server._stop.is_set())

    def test_rpc_validation_notifications_and_unknown_method(self):
        output = io.StringIO()
        server = MCPServer(FakeClient(), output)
        server._start_poller = lambda: None
        server.handle({"jsonrpc": "1.0", "id": 1, "method": "ping"})
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "unknown"})
        server.handle({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": []})
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        server.handle({"jsonrpc": "2.0", "id": 4, "method": "initialize",
                       "params": {"protocolVersion": "2025-11-25"}})
        server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": 5, "arguments": []}})
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["error"]["code"], -32600)
        self.assertEqual(rows[1]["error"]["code"], -32601)
        self.assertEqual(rows[2]["error"]["code"], -32602)
        self.assertEqual(rows[3]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(rows[4]["error"]["code"], -32602)
        server._stop.set()

    def test_rpc_rejects_non_object_missing_method_and_pre_revoked_calls(self):
        output = io.StringIO()
        server = MCPServer(FakeClient(), output)
        server._start_poller = lambda: None
        server.handle(None)
        server.handle({"jsonrpc": "2.0", "id": 1})
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["error"]["code"], -32600)
        self.assertEqual(rows[1]["error"]["code"], -32600)
        server._revoked = True
        result = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIsNone(result)
        self.assertIn("credential is no longer valid", output.getvalue())

    def test_capability_denial_is_not_mistaken_for_revocation(self):
        client = FakeClient()
        client.capabilities = lambda conv_id=None: (_ for _ in ()).throw(ApiError("Partyline HTTP 403"))
        output = io.StringIO()
        server = MCPServer(client, output)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertFalse(server._revoked)
        self.assertIn("HTTP 403", output.getvalue())

    def test_poller_handles_initial_state_and_transient_failures(self):
        class StopAfterOne:
            def __init__(self):
                self.calls = 0

            def wait(self, _seconds):
                self.calls += 1
                return self.calls > 1

        client = FakeClient()
        output = io.StringIO()
        server = MCPServer(client, output)
        server._stop = StopAfterOne()
        server._poll()
        self.assertEqual(output.getvalue(), "")
        client.capabilities = lambda conv_id=None: (_ for _ in ()).throw(RuntimeError("transient"))
        server._stop = StopAfterOne()
        server._poll()
        self.assertEqual(output.getvalue(), "")

    def test_tool_call_invalid_arguments_and_generic_failure_are_structured(self):
        client = FakeClient()
        server = MCPServer(client, io.StringIO())
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "missing", "arguments": {}}})
        first = json.loads(server.output.getvalue().splitlines()[0])
        self.assertTrue(first["result"]["isError"])
        client.request = lambda *args: (_ for _ in ()).throw(RuntimeError("secret detail"))
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "guide", "arguments": {}}})
        second = json.loads(server.output.getvalue().splitlines()[1])
        self.assertEqual(second["result"]["content"][0]["text"], "Partyline MCP operation failed")
        self.assertNotIn("secret detail", server.output.getvalue())

    def test_capability_poll_notifies_once_for_change_and_reports_revocation(self):
        class StopAfterOne:
            def __init__(self):
                self.calls = 0

            def wait(self, _seconds):
                self.calls += 1
                return self.calls > 1

        client = FakeClient(actions=("read",))
        output = io.StringIO()
        server = MCPServer(client, output)
        server._state_signature = server._signature(client.state)
        client.state["actions"].append("assign")
        server._stop = StopAfterOne()
        server._poll()
        self.assertIn("notifications/tools/list_changed", output.getvalue())
        denied = MCPServer(client, io.StringIO())
        denied._stop = StopAfterOne()
        client.capabilities = lambda conv_id=None: (_ for _ in ()).throw(ApiError("Partyline HTTP 401"))
        denied._poll()
        self.assertTrue(denied._revoked)
        self.assertIn("notifications/message", denied.output.getvalue())

    def test_demotion_and_promotion_change_catalog(self):
        client = FakeClient(actions=("read", "write"))
        client.state.update(role="implementer", is_lead=False)
        output = io.StringIO()
        server = MCPServer(client, output)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        client.state["actions"] = ["read", "write", "assign", "read_reports"]
        client.state.update(role="lead", is_lead=True)
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        client.state["actions"] = ["read"]
        client.state.update(role="implementer", is_lead=False)
        server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        first, promoted, demoted = [json.loads(line)["result"]["tools"]
                                    for line in output.getvalue().splitlines()]
        self.assertNotIn("reports", [item["name"] for item in first])
        self.assertIn("reports", [item["name"] for item in promoted])
        self.assertIn("set_goal", [item["name"] for item in promoted])
        self.assertNotIn("set_goal", [item["name"] for item in demoted])
        self.assertIn("captain", [item["name"] for item in demoted])
        self.assertNotIn("post_message", [item["name"] for item in demoted])

    def test_revoked_credential_produces_short_error_without_disclosing_token(self):
        client = FakeClient()
        client.capabilities = lambda conv_id=None: (_ for _ in ()).throw(ApiError("Partyline HTTP 401"))
        server = MCPServer(client, io.StringIO())
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertTrue(server._revoked)
        self.assertNotIn("secret", server.output.getvalue())

    def test_run_handles_parse_error_oversized_input_and_eof(self):
        output = io.StringIO()
        server = MCPServer(FakeClient(), output)
        server.run(io.StringIO("not-json\n"))
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32700)
        output = io.StringIO()
        server = MCPServer(FakeClient(), output)
        server.run(io.StringIO("x" * (server_module.MAX_LINE + 1)))
        self.assertIn("input limit", output.getvalue())

    def test_module_entrypoint_exits_with_server_status(self):
        import runpy

        with patch.object(server_module, "main", return_value=7):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_module("partyline.mcp.__main__", run_name="__main__")
        self.assertEqual(raised.exception.code, 7)

    def test_main_startup_error_and_normal_exit(self):
        with patch.object(server_module, "PartylineClient", side_effect=ValueError("missing")):
            self.assertEqual(server_module.main(), 2)
        with patch.object(server_module, "PartylineClient", return_value=FakeClient()), \
                patch.object(MCPServer, "run", return_value=None):
            self.assertEqual(server_module.main(), 0)

    def test_captain_registry_keeps_only_fixed_dispatcher_for_non_lead(self):
        self.assertEqual(tools_captain.tool_list({"kind": "machine", "role": "implementer",
                                                  "is_lead": False, "actions": ["assign"]})[
                             0]["name"], "captain")
        with self.assertRaisesRegex(ValueError, "unknown captain"):
            tools_captain.call(FakeClient(), "captain", {"op": "purge", "args": {}}, {})


if __name__ == "__main__":
    unittest.main()
