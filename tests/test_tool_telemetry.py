"""Content-free capture and deterministic lossy transport, without real waits or HTTP."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from partyline.mcp import catalog, telemetry
from partyline.mcp.client import ApiError
from partyline.mcp.image_dimensions import image_dimensions
from partyline.mcp.server import MCPServer
from partyline.tool_telemetry_contracts import ToolCall


class Timer:
    instances = []

    def __init__(self, delay, callback):
        self.delay, self.callback = delay, callback
        self.started = self.cancelled = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class CaptureTests(unittest.TestCase):
    def measure(self, name="screen_elements", args=None, value=None, error=False, media=None):
        with patch.object(telemetry.time, "perf_counter", return_value=1.125), \
                patch.object(telemetry.time, "time", return_value=500):
            return telemetry.record(name, args or {}, "éhello", value, error, 1, "claude", media)

    def test_sizes_flags_and_no_content(self):
        record = self.measure(args={"query": "private title", "value": "password", "refresh": True,
                                    "more": True, "window": "private window"})
        self.assertEqual((record["result_bytes"], record["result_chars"], record["estimated_tokens"]),
                         (7, 6, 2))
        self.assertEqual(record["latency_ms"], 125)
        self.assertEqual(record["timestamp"], 500)
        self.assertEqual((record["query"], record["refresh"], record["more"], record["then"]),
                         (True, True, True, False))
        metrics = record
        self.assertNotIn("private", json.dumps(metrics))
        self.assertNotIn("password", json.dumps(metrics))
        self.assertNotIn("éhello", json.dumps(metrics))
        ToolCall.model_validate(metrics)

    def test_operations_are_allowlisted_and_actions_unwrapped(self):
        for name, args, sub in [
                ("extras", {"op": "tool_usage", "args": {}}, "tool_usage"),
                ("captain", {"op": "set_goal", "args": {"goal": "secret"}}, "set_goal"),
                ("screen_element_action", {"action": "invoke", "then": {}}, "invoke"),
                ("extras", {"op": "screen_element_action", "args": {
                    "action": "set_value", "value": "secret", "then": {"query": "secret"}}},
                 "screen_element_action"),
                ("extras", {"op": "secret", "args": {}}, ""),
                ("extras", {"op": [], "args": []}, ""),
                ("screen_element_action", {"action": "secret"}, "")]:
            with self.subTest(name=name, args=args):
                record = self.measure(name, args)
                self.assertEqual(record["sub_op"], sub)
                metrics = {key: value for key, value in record.items() if key != "_transcript"}
                self.assertNotIn("secret", json.dumps(metrics))
        self.assertTrue(self.measure("screen_element_action", {"action": "invoke", "then": {}})["then"])
        self.assertEqual(self.measure("secret")["tool"], "unknown")
        self.assertEqual(self.measure([])["tool"], "unknown")

    def test_screen_outcomes_and_bounded_media_attribution(self):
        media = telemetry.ScreenMedia(capacity=1)
        frame = self.measure("screen_frame", value={"file": {"id": "screen-ref"}}, media=media)
        self.assertEqual((frame["outcome"], frame["media_source"], frame["images"]), ("ok", "screen", []))
        self.assertNotIn("screen-ref", json.dumps(frame))
        fetched = self.measure("get_media", args={"file_id": "screen-ref"},
                               value={"width": 750, "height": 1000}, media=media)
        self.assertEqual((fetched["media_source"], len(fetched["images"])), ("screen", 1))
        other = self.measure("get_media", args={"file_id": "other"},
                             value={"width": 10, "height": 10}, media=media)
        self.assertEqual(other["media_source"], "other")
        self.assertEqual(self.measure("screen_click", value={"status": "failed"})["outcome"], "failed")
        self.assertEqual(self.measure("screen_eval", value={"status": "unconfirmed"})["outcome"],
                         "unconfirmed")
        self.assertEqual(self.measure("screen_click", value={"status": "failed"}, error=True)["outcome"],
                         "error")
        self.assertEqual(self.measure("Bash", value={"status": "failed"})["outcome"], "ok")
        self.measure("screen_window_snapshot", value={"file": {"id": "new-ref"}}, media=media)
        evicted = self.measure("get_media", args={"file_id": "screen-ref"}, value={}, media=media)
        self.assertEqual(evicted["media_source"], "other")

    def test_image_estimators_and_delivery_boundary(self):
        self.assertEqual(telemetry.estimate_image(750, 1000, "claude")["estimated_tokens"], 1000)
        self.assertIsNone(telemetry.estimate_image(750, 1000, "codex")["estimated_tokens"])
        self.assertLessEqual(telemetry.estimate_image(4000, 3000, "claude")["estimated_tokens"], 1534)
        self.assertLessEqual(telemetry.estimate_image(4000, 100, "claude")["estimated_tokens"], 82)
        ref = {"media": {"width": 750, "height": 1000, "id": "secret"}}
        self.assertEqual(self.measure(value=ref)["images"], [])
        self.assertEqual(len(self.measure("get_media", value=ref)["images"]), 1)
        inline = {"inline": True, **ref}
        self.assertEqual(len(self.measure(value=[inline])["images"]), 1)
        self.assertEqual(len(self.measure(value={"type": "image", "width": 2, "height": 3})["images"]), 1)
        self.assertEqual(self.measure("get_media", value=ref, error=True)["images"], [])
        self.assertEqual(self.measure("get_media", value={"width": -1, "height": 5})["images"], [])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image"
            Image.new("RGB", (25, 40)).save(path, format="PNG")
            self.assertEqual(image_dimensions(path), {"width": 25, "height": 40})
            path.write_text("not an image")
            self.assertEqual(image_dimensions(path), {})
            with patch("partyline.mcp.image_dimensions.Image.open", side_effect=ValueError("bad plugin")):
                self.assertEqual(image_dimensions(path), {})

    def test_one_record_for_success_and_every_error_path(self):
        client = SimpleNamespace(connection={"api": "http://lan.example"}, capabilities=Mock(return_value={}))
        server = MCPServer(client, io.StringIO())
        server.telemetry = Mock()
        for outcome in ({"ok": "secret"}, ApiError("secret"), ValueError("secret"),
                        OSError("secret"), TypeError("secret"), RuntimeError("secret")):
            with self.subTest(outcome=outcome), patch.object(catalog, "dispatch") as dispatch:
                if isinstance(outcome, Exception):
                    dispatch.side_effect = outcome
                else:
                    dispatch.return_value = outcome
                server._call(1, {"name": "whoami", "arguments": {}})
        server._call(2, {"name": "whoami", "arguments": []})
        self.assertEqual(server.telemetry.enqueue.call_count, 7)
        records = [call.args[0] for call in server.telemetry.enqueue.call_args_list]
        self.assertEqual(sum(row["is_error"] for row in records), 6)
        self.assertNotIn("secret", json.dumps(records))
        server.telemetry.enqueue.side_effect = RuntimeError("broken telemetry")
        with patch.object(catalog, "dispatch", return_value={}):
            server._call(3, {"name": "whoami"})
        last = json.loads(server.output.getvalue().splitlines()[-1])["result"]
        self.assertFalse(last.get("isError", False))

    def test_tool_usage_extras_works_without_captain(self):
        client = SimpleNamespace(home="plain", request=Mock(return_value={"rows": []}))
        state = {"kind": "machine", "role": "worker", "actions": ["read", "write"]}
        self.assertIn("tool_usage", catalog.guide_index(state)["tools"][0]["name"])
        self.assertEqual(catalog.dispatch(client, "extras", {"op": "tool_usage", "args": {
            "include_descendants": True, "group": "tool", "since": 100}}, state), {"rows": []})
        self.assertIn("include_descendants=true", client.request.call_args.args[1])
        with self.assertRaises(ValueError):
            catalog.dispatch(client, "extras", {"op": "tool_usage", "args": {"since": "bad"}}, state)


class TransportTests(unittest.TestCase):
    def setUp(self):
        Timer.instances.clear()
        self.client = SimpleNamespace(request=Mock())
        self.transport = telemetry.Telemetry(self.client, capacity=3, batch_size=2, timer=Timer)

    def test_deadline_batch_shutdown_and_drop(self):
        with patch.object(telemetry.threading, "Thread") as thread:
            self.transport.enqueue({"n": 1})
            self.assertEqual(len(Timer.instances), 1)
            self.transport.enqueue({"n": 2})
            self.assertTrue(Timer.instances[0].cancelled)
            self.assertEqual(thread.call_count, 1)
            self.transport.enqueue({"n": 3})
            self.transport.enqueue({"n": 4})
            self.assertEqual(len(self.transport.queue), 3)
            self.client.request.assert_not_called()
        self.transport._send()
        self.assertEqual([len(c.args[2]["records"]) for c in self.client.request.call_args_list], [2, 1])
        self.assertIsNone(self.transport.worker)
        self.client.request.side_effect = OSError("failed")
        self.transport.enqueue({"n": 5})
        with patch.object(telemetry.threading, "Thread"):
            Timer.instances[-1].callback()
        self.transport._send()
        self.assertEqual(len(self.transport.queue), 0)
        self.transport.worker = Mock()
        self.transport.close()
        self.transport.worker.join.assert_called_once_with(timeout=1.1)
        self.transport.enqueue({"n": 6})
        self.assertEqual(len(self.transport.queue), 0)

    def test_empty_flush_and_shutdown_final_batch(self):
        self.transport.flush()
        self.assertIsNone(self.transport.worker)
        self.transport.close()
        fresh = telemetry.Telemetry(self.client, timer=Timer)
        fresh.enqueue({"n": 1})
        with patch.object(telemetry.threading, "Thread") as thread:
            fresh.close()
            self.assertTrue(Timer.instances[-1].cancelled)
            thread.return_value.join.assert_called_once_with(timeout=1.1)
        fresh._send()
        self.assertEqual(self.client.request.call_count, 1)

    def test_first_record_deadline_is_not_reset(self):
        transport = telemetry.Telemetry(self.client, batch_size=10, timer=Timer)
        transport.enqueue({"n": 1})
        deadline = Timer.instances[-1]
        transport.enqueue({"n": 2})
        self.assertIs(Timer.instances[-1], deadline)
        self.assertEqual(len(Timer.instances), 1)
        self.assertTrue(deadline.started)
        with patch.object(telemetry.threading, "Thread"):
            deadline.callback()
        self.assertTrue(deadline.cancelled)
        transport._send()
        self.assertIsNone(transport.worker)
        self.assertEqual(len(Timer.instances), 1)
        self.assertEqual(telemetry.estimate_text_tokens(0), 0)
        self.assertEqual(telemetry.estimate_text_tokens(4), 1)
        self.assertEqual(telemetry.estimate_text_tokens(5), 2)
