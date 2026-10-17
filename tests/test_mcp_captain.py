import io
import json
import unittest

from partyline.mcp.client import ApiError
from partyline.mcp.server import MCPServer
from partyline.mcp import tools_captain


class Client:
    def __init__(self):
        self.home = "home"
        self.connection = {"api": "http://127.0.0.1", "attachment_id": "att"}
        self.state = {"kind": "machine", "role": "lead", "is_lead": True,
                      "conv_id": "home", "attachment_id": "att",
                      "actions": ["read", "assign", "write", "attach", "close",
                                  "create_child", "appoint_lead", "archive", "accept",
                                  "read_reports"]}
        self.target = {**self.state, "conv_id": "child"}
        self.calls = []

    def capabilities(self, conv_id=None):
        if conv_id and conv_id != self.home:
            return self.target
        return self.state

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith("/children"):
            return [{"id": "child"}]
        return {"ok": True}


class CaptainToolTests(unittest.TestCase):
    def test_dispatcher_is_always_listed_and_named_tools_follow_live_lead(self):
        client = Client()
        self.assertIn("captain", {tool["name"] for tool in tools_captain.tool_list(client.state)})
        self.assertIn("attach_worker", {tool["name"] for tool in tools_captain.tool_list(client.state)})
        worker = {**client.state, "role": "implementer", "is_lead": False}
        self.assertEqual([tool["name"] for tool in tools_captain.tool_list(worker)], ["captain"])

    def test_unknown_dispatch_is_rejected_without_api_call(self):
        client = Client()
        with self.assertRaisesRegex(ValueError, "unknown captain"):
            tools_captain.call(client, "captain", {"op": "DELETE", "args": {
                "path": "/api/conversations/home"}}, client.state)
        self.assertEqual(client.calls, [])

    def test_dispatcher_denies_non_lead_and_target_line_authorization(self):
        client = Client()
        worker = {**client.state, "role": "implementer", "is_lead": False}
        with self.assertRaisesRegex(ApiError, "not a line captain"):
            tools_captain.call(client, "captain", {"op": "set_goal", "args": {
                "conv_id": "home", "goal": "x"}}, worker)
        client.target = {**client.target, "actions": ["read"]}
        with self.assertRaisesRegex(ApiError, "not authorized"):
            tools_captain.call(client, "captain", {"op": "set_goal", "args": {
                "conv_id": "child", "goal": "x"}}, client.state)
        self.assertEqual(client.calls, [])

    def test_demoted_cached_named_tool_is_denied_without_side_effect(self):
        client = Client()
        out = io.StringIO()
        server = MCPServer(client, out)
        client.state = {**client.state, "role": "implementer", "is_lead": False}
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "captain", "arguments": {"op": "set_goal", "args": {
                "conv_id": "home", "goal": "no"}}}})
        answer = json.loads(out.getvalue())["result"]
        self.assertTrue(answer["isError"])
        self.assertEqual(client.calls, [])

    def test_revoked_credential_while_connected_blocks_dispatch(self):
        client = Client()
        out = io.StringIO()
        server = MCPServer(client, out)
        client.capabilities = lambda *_args: (_ for _ in ()).throw(ApiError("Partyline HTTP 401"))
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "captain", "arguments": {"op": "set_goal", "args": {
                "conv_id": "home", "goal": "no"}}}})
        self.assertTrue(server._revoked)
        self.assertEqual(client.calls, [])

    def test_guide_only_returns_current_operations_and_schemas(self):
        client = Client()
        guide = tools_captain.guide(client.state)
        names = {row["name"] for row in guide["operations"]}
        self.assertIn("set_goal", names)
        self.assertNotIn("purge", names)
        self.assertEqual(guide["fallback"]["name"], "captain")
        self.assertNotIn("path", guide["fallback"]["inputSchema"]["properties"])

    def test_retire_child_is_limited_to_direct_child_and_one_line(self):
        client = Client()
        client.target = {**client.state, "actions": ["archive"]}
        tools_captain.call(client, "captain", {"op": "retire_child", "args": {
            "conv_id": "child", "stop_processes": True}}, client.state)
        self.assertEqual(client.calls[-1], ("DELETE", "/api/conversations/child?stop_processes=true", None))
        client.calls.clear()
        with self.assertRaisesRegex(ApiError, "direct child"):
            tools_captain.call(client, "captain", {"op": "retire_child", "args": {
                "conv_id": "outside"}}, client.state)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
