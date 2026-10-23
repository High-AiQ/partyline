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

    def test_dispatcher_reaches_task_operations_a_client_that_never_relists_cannot_see(self):
        client = Client()
        root = {**client.state, "actions": [*client.state["actions"], "create_task", "tasks"]}
        fallback = tools_captain.guide(root)["fallback"]["inputSchema"]
        self.assertIn("create_task", fallback["properties"]["op"]["enum"])
        tools_captain.call(client, "captain", {"op": "create_task", "args": {
            "name": "slice", "goal": "build it", "implementer": "builder"}}, root)
        self.assertEqual(client.calls[-1][:2], ("POST", "/api/conversations/home/tasks"))
        with self.assertRaisesRegex(ApiError, "not currently available"):
            tools_captain.call(client, "captain", {"op": "create_task", "args": {
                "name": "slice", "goal": "build it", "implementer": "builder"}}, client.state)

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

    def test_reports_use_lead_dispatcher_with_live_scope_and_schema(self):
        client = Client()
        client.state["actions"].append("notify")
        names = [tool["name"] for tool in tools_captain.tool_list(client.state)]
        self.assertEqual(names.count("reports"), 1)
        tools_captain.call(client, "captain", {"op": "reports", "args": {
            "operation": "list"}}, client.state)
        tools_captain.call(client, "reports", {"operation": "post", "body": "status",
            "notify": True}, client.state)
        self.assertEqual(client.calls[-2:], [
            ("GET", "/api/conversations/home/reports", None),
            ("POST", "/api/conversations/home/reports", {"body": "status", "notify": True}),
        ])
        with self.assertRaisesRegex(ValueError, "allowed length"):
            tools_captain.call(client, "captain", {"op": "reports", "args": {
                "operation": "post", "body": "x" * 2001}}, client.state)
        denied = {**client.state, "actions": ["read", "report"]}
        with self.assertRaisesRegex(ApiError, "cannot read"):
            tools_captain.call(client, "captain", {"op": "reports", "args": {
                "operation": "list"}}, denied)
        with self.assertRaisesRegex(ApiError, "cannot post"):
            tools_captain.call(client, "captain", {"op": "reports", "args": {
                "operation": "post", "body": "status", "notify": True}}, denied)

    def test_reports_get_and_paged_list_reach_fixed_routes(self):
        client = Client()
        tools_captain.call(client, "captain", {"op": "reports", "args": {
            "operation": "list", "limit": 5, "before_id": 9}}, client.state)
        tools_captain.call(client, "reports", {"operation": "get", "report_id": 7}, client.state)
        self.assertEqual(client.calls[-2:], [
            ("GET", "/api/conversations/home/reports?limit=5&before_id=9", None),
            ("GET", "/api/conversations/home/reports/7", None),
        ])
        with self.assertRaisesRegex(ValueError, "report_id is required"):
            tools_captain.call(client, "reports", {"operation": "get"}, client.state)

    def test_validation_errors_name_the_operation_and_fields(self):
        client = Client()
        with self.assertRaisesRegex(
                ValueError, r"captain op 'accept': unknown field\(s\) findings_text; "
                r"missing required field\(s\) sha; accepted fields: conv_id, sha, allow_descendant, "
                "findings, run_gates"):
            tools_captain.call(client, "captain", {"op": "accept", "args": {
                "conv_id": "c", "findings_text": "x"}}, client.state)
        with self.assertRaisesRegex(ValueError, r"captain op 'accept': missing required field\(s\) sha;"):
            tools_captain.call(client, "captain", {"op": "accept", "args": {"conv_id": "c"}}, client.state)
        with self.assertRaisesRegex(ValueError, r"captain op 'accept': unknown field\(s\) extra;"):
            tools_captain.call(client, "captain", {"op": "accept", "args": {
                "conv_id": "c", "sha": "abcd", "extra": 1}}, client.state)
        with self.assertRaisesRegex(ValueError, "captain op 'accept': sha exceeds"):
            tools_captain.call(client, "captain", {"op": "accept", "args": {
                "conv_id": "c", "sha": "x" * 65}}, client.state)

    def test_reports_fallback_is_denied_after_demotion_and_revocation(self):
        client = Client()
        output = io.StringIO()
        server = MCPServer(client, output)
        client.state = {**client.state, "role": "implementer", "is_lead": False}
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "captain", "arguments": {"op": "reports", "args": {
                "operation": "list"}}}})
        self.assertTrue(json.loads(output.getvalue())["result"]["isError"])
        self.assertEqual(client.calls, [])
        client.capabilities = lambda *_args: (_ for _ in ()).throw(ApiError("Partyline HTTP 401"))
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "captain", "arguments": {"op": "reports", "args": {
                "operation": "list"}}}})
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

    def test_root_retirement_preview_and_explicit_force_fields(self):
        client = Client()
        client.state["parent_id"] = None
        tools_captain.call(client, "retirement_preview", {
            "conv_id": "grandchild", "include_children": True}, client.state)
        self.assertEqual(client.calls[-1], (
            "GET", "/api/conversations/grandchild/retirement-preview?include_children=true", None))
        tools_captain.call(client, "retire_child", {"conv_id": "grandchild", "force_discard": True,
            "include_children": True, "clear_goal": True, "preview_token": "abc"}, client.state)
        method, path, _ = client.calls[-1]
        self.assertEqual(method, "DELETE")
        self.assertIn("force_discard=true", path)
        self.assertIn("preview_token=abc", path)
        self.assertIn("clear_goal=true", path)

    def test_retirement_tool_descriptions_explain_discard_and_recovery(self):
        tools = {tool["name"]: tool for tool in tools_captain.tool_list(Client().state)}
        self.assertIn("Ignored files are lost", tools["retire_child"]["description"])
        self.assertIn("principal-bound", tools["retirement_preview"]["description"])

    def test_write_set_requests_lists_pending_and_bounded_grants(self):
        client = Client()
        pending = {"request": {"id": "req-1", "path": "/work", "requester": "worker"}}
        grants = [{"path": f"/grant/{n}", "granted_by": "person", "granted_at": n,
                   "docker_mode": "managed", "extra": "not exposed"}
                  for n in range(75)]

        def request(method, path, payload=None):
            client.calls.append((method, path, payload))
            return pending if path.endswith("/write-set/request") else grants

        client.request = request
        result = tools_captain.call(client, "write_set_requests", {"conv_id": "child"},
                                    client.state)
        self.assertEqual(result["request"], pending["request"])
        self.assertEqual(len(result["grants"]), 50)
        self.assertTrue(result["grants_truncated"])
        self.assertNotIn("extra", result["grants"][0])
        self.assertEqual(client.calls, [
            ("GET", "/api/conversations/child/write-set/request", None),
            ("GET", "/api/conversations/child/write-set", None),
        ])
        self.assertIn("write_set_requests", {tool["name"]
                                             for tool in tools_captain.tool_list(client.state)})
        self.assertIn("write_set_requests", {row["name"]
                                             for row in tools_captain.guide(client.state)["operations"]})
        dispatched = tools_captain.call(client, "captain", {"op": "write_set_requests",
                                      "args": {"conv_id": "child"}}, client.state)
        self.assertEqual(dispatched["request"], pending["request"])

    def test_write_set_requests_requires_target_read_and_lead_dispatcher(self):
        client = Client()
        client.target = {**client.target, "actions": []}
        with self.assertRaisesRegex(ApiError, "not authorized"):
            tools_captain.call(client, "write_set_requests", {"conv_id": "child"}, client.state)
        worker = {**client.state, "role": "implementer", "is_lead": False}
        with self.assertRaisesRegex(ApiError, "not a line captain"):
            tools_captain.call(client, "captain", {"op": "write_set_requests", "args": {
                "conv_id": "home"}}, worker)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
