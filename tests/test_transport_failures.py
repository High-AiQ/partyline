"""A timeout or reset is reported as one, never as bad arguments; no real waits."""

import contextlib
import http.client
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from partyline import agent_client
from partyline.agent_client import classify_failure, failure_text
from partyline.agent_connection import provision_connection
from partyline.mcp.server import MCPServer
from tests.test_mcp import FakeClient

SECRET = "private-test-token"


def raising(exc):
    def fail(*args, **kwargs):
        raise exc
    return fail


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "timeout": [TimeoutError(), TimeoutError(), URLError(TimeoutError()),
                        URLError("timed out")],
            "refused": [ConnectionRefusedError(), URLError(ConnectionRefusedError())],
            "reset": [ConnectionResetError(), BrokenPipeError(), http.client.RemoteDisconnected(),
                      http.client.IncompleteRead(b"")],
            "network": [socket.gaierror(), URLError("unreachable"), OSError(113, "no route")],
            "local": [FileNotFoundError(), PermissionError(), ValueError(), OSError(5, "io")],
        }
        for kind, errors in cases.items():
            for exc in errors:
                with self.subTest(kind=kind, exc=repr(exc)):
                    self.assertEqual(classify_failure(exc), kind)

    def test_a_write_may_have_landed_but_a_read_or_refusal_did_not_change_anything(self):
        self.assertIn("may already have been applied", failure_text("timeout", changes_state=True))
        self.assertNotIn("may already", failure_text("timeout", changes_state=False))
        self.assertIn("nothing was sent", failure_text("refused", changes_state=True))


class McpFailureTests(unittest.TestCase):
    def call(self, client, name, args, server=None):
        server = server or MCPServer(client, io.StringIO())
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}})
        row = json.loads(server.output.getvalue().splitlines()[-1])
        return row["result"]["content"][0]["text"], row["result"].get("isError", False), server

    def test_a_timed_out_decision_says_it_may_have_been_applied(self):
        client = FakeClient()
        timeout = TimeoutError("timed out reading http://x/?token=" + SECRET)
        timeout.partyline_method = "POST"
        client.request = raising(timeout)
        text, error, _ = self.call(client, "captain", {"op": "decide_write_set", "args": {
            "conv_id": "child", "request_id": "r", "decision": "approve", "reason": "private"}})
        self.assertTrue(error)
        self.assertIn("timed out", text)
        self.assertIn("may already have been applied", text)
        self.assertIn("read the request or task", text)
        self.assertNotIn("invalid tool arguments", text)
        for leak in (SECRET, "private", "http://x"):
            self.assertNotIn(leak, text)

    def test_a_timed_out_read_is_safe_to_repeat(self):
        client = FakeClient()
        timeout = TimeoutError()
        timeout.partyline_method = "GET"
        client.request = raising(timeout)
        text, _, _ = self.call(client, "whoami", {})
        self.assertIn("retrying is safe", text)
        self.assertNotIn("may already", text)

    def test_connection_refused_and_reset_are_named(self):
        for exc, phrase in ((ConnectionRefusedError(), "refused the connection"),
                            (ConnectionResetError(), "reset or closed"),
                            (http.client.IncompleteRead(b"x"), "reset or closed")):
            client = FakeClient()
            client.request = raising(exc)
            with self.subTest(exc=type(exc).__name__):
                text, error, _ = self.call(client, "whoami", {})
                self.assertTrue(error)
                self.assertIn(phrase, text)

    def test_real_local_file_errors_keep_the_argument_message(self):
        for exc in (FileNotFoundError("/secret/path"), PermissionError("denied")):
            client = FakeClient()
            client.request = raising(exc)
            text, _, _ = self.call(client, "whoami", {})
            self.assertEqual(text, "invalid tool arguments or local file")

    def test_create_task_keeps_its_retry_advice(self):
        client = FakeClient()
        client.state["actions"] += ["create_task", "tasks"]
        client.request = raising(TimeoutError())
        text, _, _ = self.call(client, "captain", {"op": "create_task", "args": {
            "name": "slice", "goal": "build it", "implementer": "builder"}})
        self.assertIn("the task may already exist", text)

    def test_a_slow_capability_read_is_reported_before_the_tool_ran(self):
        client = FakeClient()
        client.capabilities = raising(TimeoutError())
        text, error, _ = self.call(client, "captain", {"op": "decide_write_set", "args": {}})
        self.assertTrue(error)
        self.assertIn("did not run", text)
        self.assertIn("timed out", text)
        self.assertNotIn("may already have been applied", text)

    def test_guide_is_answered_from_the_last_capabilities_when_the_server_is_slow(self):
        client = FakeClient()
        _, _, server = self.call(client, "whoami", {})
        client.capabilities = raising(TimeoutError())
        text, error, _ = self.call(client, "guide", {"topic": "complete_handover"}, server)
        self.assertFalse(error, text)
        self.assertIn("complete_handover", text)
        # Never run, never cached: it reports the timeout instead of guessing.
        fresh = FakeClient()
        fresh.capabilities = raising(TimeoutError())
        text, error, _ = self.call(fresh, "guide", {"topic": "complete_handover"})
        self.assertTrue(error)
        self.assertIn("timed out", text)


class AgentClientFailureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db = str(Path(directory.name) / "t.db")
        provision_connection(db, {"id": "a", "conv_id": "c", "name": "n", "api_token": SECRET,
                                  "hook_url": "http://127.0.0.1:8643/api/hooks/a"})
        self.connection = str(Path(db + ".agent-connections/a.json"))
        self.body = Path(directory.name) / "body.json"
        self.body.write_text('{"reason": "private-reason"}')

    def run_main(self, method, path, exc, *extra):
        error = io.StringIO()
        with patch.object(agent_client, "api_request", raising(exc)), \
                contextlib.redirect_stderr(error):
            code = agent_client.main(["--connection", self.connection, "request", method, path,
                                      *extra])
        self.assertEqual(code, 1)
        for leak in (SECRET, "private-reason"):
            self.assertNotIn(leak, error.getvalue())
        return error.getvalue()

    def test_a_timed_out_post_says_it_may_have_been_applied(self):
        for exc in (TimeoutError(SECRET), URLError(TimeoutError(SECRET))):
            text = self.run_main("POST", "/api/x/deny", exc, "--json-file", str(self.body))
            self.assertIn("timed out", text)
            self.assertIn("may already have been applied", text)

    def test_a_timed_out_get_is_safe_to_repeat(self):
        text = self.run_main("GET", "/api/x", TimeoutError())
        self.assertIn("retrying is safe", text)
        self.assertNotIn("may already", text)

    def test_refused_and_reset_are_distinct(self):
        self.assertIn("refused the connection",
                      self.run_main("POST", "/api/x", ConnectionRefusedError()))
        self.assertIn("reset or closed", self.run_main("POST", "/api/x", ConnectionResetError()))

    def test_bad_local_input_is_not_called_a_network_failure(self):
        bad = Path(self.body.parent / "bad.json")
        bad.write_text("{nope private-reason")
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = agent_client.main(["--connection", self.connection, "request", "POST",
                                      "/api/x", "--json-file", str(bad)])
        self.assertEqual(code, 1)
        self.assertIn("bad local request input", error.getvalue())
        self.assertNotIn("private-reason", error.getvalue())
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            agent_client.main(["--connection", str(bad.parent / "missing.json"), "request",
                               "GET", "/api/x"])
        self.assertIn("bad local connection file", error.getvalue())


if __name__ == "__main__":
    unittest.main()
