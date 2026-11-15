"""Combined window looks and marks retain one capture generation and use guarded actions."""
import base64
import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.mcp import catalog, tools_screen
from partyline.mcp.server import MCPServer
from partyline.mcp.client import ApiError
from partyline.screen_look_data import candidates, inputs, line
from partyline.screen_tree import Node
from partyline.screen_window_snapshot import image_tokens
from tests.test_window_snapshot import SnapshotFixture


class LookDataTests(unittest.TestCase):
    def test_visible_bounds_include_non_actionable_and_query_filters_before_cap(self):
        elements = [{"id": str(i), "name": str(i), "bounds": [0, 0, 30 + i, 30 + i]} for i in range(90)]
        elements += [{"id": "action", "actions": ["invoke"], "bounds": [0, 0, 200, 200]},
                     {"id": "hidden", "hidden": True, "bounds": [0, 0, 50, 50]},
                     {"id": "off", "offscreen": True, "bounds": [0, 0, 50, 50]},
                     {"id": "empty", "bounds": [0, 0, 0, 20]}]
        found = candidates(elements)
        self.assertEqual(["action", "0", "1"], [row[2].id for row in found[:3]])
        self.assertEqual(91, len(found))
        self.assertEqual("89", inputs(candidates(elements, "=89"), 81)[0]["id"])
        self.assertIn("no actions", line(2, found[1][2]))
        self.assertEqual([], candidates([{"id": "no-bounds"}]))

    def test_compact_state(self):
        node = Node({"control_type": "Button", "name": 'Save\n"copy"', "actions": ["invoke", "press"],
                     "focused": True, "enabled": False, "toggle": 1, "selected": False, "value": "ready"})
        text = line(7, node)
        for part in ('[7] Button "Save', 'invoke,press', 'focused', 'disabled', 'checked=true',
                     'selected=false', 'value="ready"'):
            self.assertIn(part, text)


class WindowLookTests(SnapshotFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.device.update(windows=5)
        self.geometry = {"rect": [0, 0, 400, 300], "size": [400, 300],
                         "regions": [[0, 0, 400, 300]], "dpi": 96}
        self.raw = [{"id": "named", "control_type": "Button", "name": "Save", "actions": ["invoke"],
                     "bounds": [10, 10, 40, 40]},
                    {"id": "plain", "name": "Decoration", "bounds": [50, 50, 100, 100]}]
        self.generation = 0
        await self.grant("a")

    async def receive(self, message):
        self.sent.append(message)
        if message["type"] == "look_window":
            self.generation += 1
            start = 1 + (self.generation - 1) * 80
            found = candidates(self.raw, message.get("query"))
            marks = [{"n": start + i, "id": row[2].id, "box": list(row[4])}
                     for i, row in enumerate(found[:80])]
            await self.hub.snapshots.from_helper(self.device, {
                "request_id": message["request_id"], "ok": True, "mime": "image/webp", "media": True,
                "snapshot_id": "snap" + str(self.generation), "geometry": self.geometry,
                "look": {"generation": str(self.generation), "snapshot_id": "tree" + str(self.generation),
                         "elements": self.raw, "truncated": len(found) > 80,
                         "changing": getattr(self, "changing", False)}, "marks": marks})
        elif message["type"] in ("window_element_action", "window_click"):
            self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                                                   "status": "completed"})
        elif message["type"] == "read_window_elements":
            self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                                                   "snapshot_id": "later",
                                                   "elements": self.raw})
        elif message["type"] == "snapshot_window":
            await self.hub.snapshots.from_helper(self.device, {"request_id": message["request_id"],
                                                               "ok": False, "error": "no capture"})

    async def look(self, ident="a", **params):
        return await self.client.post("/api/conversations/alpha/screen-window-look", params=params,
                                      headers=self.machine(ident))

    async def action(self, mark=1, **extra):
        return await self.client.post("/api/conversations/alpha/screen-control/element-action",
            headers=self.machine("a"), json={"mark": mark, "action": "invoke", **extra})

    async def test_one_round_trip_generation_and_list_match_boxes(self):
        response = await self.look()
        self.assertEqual(200, response.status_code, response.text)
        look = response.json()
        self.assertEqual("1", look["generation"])
        self.assertEqual(["look_window"], [m["type"] for m in self.sent if m["type"] == "look_window"])
        self.assertEqual([1, 2], [mark["n"] for mark in look["marks"]])
        self.assertTrue(look["lines"][0].startswith('[1] Button "Save" invoke'))
        self.assertIn("no actions", look["lines"][1])
        self.assertEqual("snap1", look["snapshot"])
        self.assertEqual({"edge": 1000, "pixels": 700_000}, self.sent[-1]["fit"])
        self.assertEqual(image_tokens(400, 300), look["image_tokens"])
        self.assertIn("pixels", look["coordinates"])

    async def test_mark_uses_named_action_with_generation_and_existing_target_mapping(self):
        await self.look()
        response = await self.action()
        self.assertEqual("completed", response.json()["status"])
        sent = [m for m in self.sent if m["type"] == "window_element_action"][-1]
        self.assertEqual(("named", "1", "invoke"),
                         (sent["element_id"], sent["look_generation"], sent["action"]))

    async def test_mark_falls_back_to_exact_point_operation_for_invoke_and_click(self):
        for action in ("invoke", "click"):
            look = (await self.look(query="Decoration")).json()
            response = await self.action(mark=look["marks"][0]["n"], action=action)
            self.assertEqual("completed", response.json()["status"], response.text)
            sent = [m for m in self.sent if m["type"] == "window_click"][-1]
            self.assertEqual((75, 75, look["snapshot"], look["generation"]),
                             (sent["x"], sent["y"], sent["snapshot"], sent["look_generation"]))
            self.assertEqual([75, 75], sent["screen"])
            self.assertEqual(40, sent["budget"])

    async def test_stale_after_new_look_and_peer_cannot_reuse(self):
        for change in ("look", "peer"):
            look = (await self.look()).json()
            mark = look["marks"][0]["n"]
            if change == "look":
                await self.look()
            else:
                await self.look("peer")
            response = await self.action(mark)
            self.assertEqual(409, response.status_code, (change, response.text))
            self.assertIn("take a fresh screen_window_look", response.text)

    async def test_unrelated_events_and_fresh_reads_keep_named_marks_usable(self):
        await self.look()
        self.raw.insert(0, {"id": "root", "control_type": "Window", "name": "Editor"})
        for _ in range(3):
            self.hub.elements.changed("g1")
            response = await self.action(1)
            self.assertEqual("completed", response.json()["status"], response.text)
        self.assertTrue(any(m["type"] == "read_window_elements" for m in self.sent))
        self.assertEqual(["named"] * 3, [m["element_id"] for m in self.sent
                                        if m["type"] == "window_element_action"])
        with patch.object(self.hub.elements, "action_target", AsyncMock(return_value=(None, False))):
            response = await self.action(1)
        self.assertEqual("failed", response.json()["status"])
        self.assertFalse(any(m["type"] == "window_click" for m in self.sent))

    async def test_named_mark_keeps_source_scoped_event_validation(self):
        await self.look()
        tree = self.hub.elements.snapshots["g1"]
        tree.sources, tree.event_counter = True, 4
        receive = self.device["socket"].send_json
        async def events(message):
            if message.get("event_status"):
                self.sent.append(message)
                self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                    "event_counter": 5, "events_supported": True, "subscription_live": True,
                    "event_sources": {"ids": [["clock"]], "unsure": []}})
            else:
                await receive(message)
        self.device["socket"].send_json = events
        self.hub.elements.changed("g1")
        response = await self.action(1)
        self.assertEqual("completed", response.json()["status"], response.text)
        reads = [m for m in self.sent if m["type"] == "read_window_elements"]
        self.assertEqual(1, len(reads))
        self.assertEqual(4, reads[0]["events_since"])
        self.assertTrue(reads[0]["event_status"])

    async def test_unrelated_events_keep_point_marks_usable_without_duplicate_standing_audit(self):
        await self.look()
        self.hub.elements.changed("g1")
        for _ in range(2):
            response = await self.action(2)
            self.assertEqual("completed", response.json()["status"], response.text)
        entries = [row["entry"] for row in self.db._exec("SELECT entry FROM screen_control_audit").fetchall()]
        standing = [row for row in entries if row.startswith(("uia_action:", "point_click:"))]
        self.assertEqual(4, len(standing))  # one start and one terminal row per point call
        self.assertTrue(all(row.startswith("point_click:") for row in standing))

    async def test_changing_capture_note_is_delivered_with_the_image_and_list(self):
        self.changing = True
        response = await self.look()
        self.assertEqual(200, response.status_code, response.text)
        look = response.json()
        self.assertIn("window changed during capture", look["changing"])
        self.assertEqual(len(look["marks"]), len(look["lines"]))

    async def test_truncation_and_query(self):
        self.raw = [{"id": str(i), "name": str(i), "bounds": [0, 0, 20, 20]} for i in range(100)]
        look = (await self.look()).json()
        self.assertEqual((80, 80), (len(look["marks"]), len(look["lines"])))
        self.assertIn("truncated", look["marks_note"])
        look = (await self.look(query="=99", detail="full")).json()
        self.assertEqual(1, len(look["lines"]))
        self.assertNotIn("marks_note", look)
        self.assertIsNone(self.sent[-1]["fit"])
        self.assertIn("pixels", look["coordinates"])  # also on unchanged images

    async def test_invalid_targets_actions_parameters_and_old_helper(self):
        for body in ({"action": "invoke"}, {"element_id": "x", "mark": 1, "action": "invoke"},
                     {"element_id": "x", "action": "click"}):
            response = await self.client.post("/api/conversations/alpha/screen-control/element-action",
                                              headers=self.machine("a"), json=body)
            self.assertEqual(422, response.status_code)
        await self.look()
        self.assertEqual(409, (await self.action(2, action="toggle")).status_code)
        self.assertEqual(409, (await self.action(2, value="bad")).status_code)
        self.device["windows"] = 4
        self.assertEqual(409, (await self.look()).status_code)

    async def test_geometry_guard_is_shared_and_race_at_point_lock_is_refused(self):
        await self.look()
        self.hub.snapshots.geometry.end("g1")
        response = await self.action(2)
        self.assertEqual("stale", response.json()["reason"])
        self.assertFalse(any(m["type"] == "window_click" for m in self.sent))
        look = (await self.look()).json()
        original = self.hub.elements.locked
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def changed(gid):
            async with original(gid):
                self.hub.snapshots.looks.latest[gid]["generation"] = "newer"
                yield
        with patch.object(self.hub.elements, "locked", changed):
            response = await self.action(look["marks"][1]["n"])
        self.assertEqual(409, response.status_code)
        entries = [row["entry"] for row in self.db._exec("SELECT entry FROM screen_control_audit").fetchall()]
        self.assertFalse(any('"route":"pending"' in row for row in entries))
        self.assertFalse(any(row.startswith("point_click:") for row in entries))

    async def test_mcp_delivers_one_image_and_full_text_and_lists_at_window_grants(self):
        value = (await self.look()).json()
        value["lines"] = ["x" * 300 for _ in range(80)]
        value["changing"] = "window changed during capture"
        state = {"actions": ["read", "write"], "conv_id": "alpha", "dynamic_screen_tools": True,
                 "screen_windows": True}
        client = SimpleNamespace(connection={"api": "http://test"}, capabilities=lambda: state,
                                 home="alpha", request=Mock(return_value=value),
                                 _send=Mock(return_value=self.image))
        listed = {t["name"] for t in catalog.listed(state)}
        self.assertIn("screen_window_look", listed)
        self.assertNotIn("screen_frame", listed)
        server = MCPServer(client, io.StringIO())
        result = server._execute({"name": "screen_window_look", "arguments": {"window": "g1"}})
        self.assertEqual(["text", "image"], [c["type"] for c in result["content"]])
        self.assertEqual(80, result["content"][0]["text"].count("x" * 300))
        self.assertIn("window changed during capture", result["content"][0]["text"])
        self.assertEqual(self.image, base64.b64decode(result["content"][1]["data"]))
        self.assertEqual("image/webp", result["content"][1]["mimeType"])
        client.request.assert_called_with("POST", "/api/conversations/alpha/screen-window-look?window=g1",
                                          timeout=100)
        client.capabilities = lambda: {**state, "dynamic_screen_tools": False}
        result = server._execute({"name": "extras", "arguments": {"op": "screen_window_look", "args": {}}})
        self.assertEqual(["text", "image"], [c["type"] for c in result["content"]])
        with self.assertRaises(ApiError):
            tools_screen.call(client, "screen_window_look", {}, {"dynamic_screen_tools": True}, "alpha")

    async def test_point_fallback_then_reads_text_and_slim_detail_and_bad_query(self):
        look = (await self.look(query="Decoration", detail="slim")).json()
        self.assertEqual({"edge": 1600, "pixels": 2_560_000}, self.sent[-1]["fit"])
        response = await self.action(mark=look["marks"][0]["n"], then={})
        self.assertEqual("completed", response.json()["status"])
        self.assertIn("after", response.json())
        self.assertNotIn("screenshot", response.json())
        self.assertEqual(422, (await self.look(query="x" * 201)).status_code)

    async def test_revocation_bad_capture_geometry_and_timeout_deliver_no_look(self):
        for answer in ({"ok": False, "error": "closed"}, {"ok": True, "look": {"generation": "x"}}):
            with patch.object(self.hub.elements, "exchange", AsyncMock(return_value=answer)):
                self.assertEqual(409, (await self.look()).status_code)
        with patch.object(self.hub.elements, "exchange", AsyncMock(side_effect=TimeoutError)):
            self.assertEqual(409, (await self.look()).status_code)
        await self.hub.window_grants.revoke("g1")
        self.assertEqual(403, (await self.look()).status_code)
        self.assertNotIn("g1", self.hub.snapshots.looks.latest)
