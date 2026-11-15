"""Scroll, drag, type and key on the server, the failure picture, the thumb budget and the compact answers."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from partyline.mcp import tools_control, tools_point
from partyline.screen_failure_snapshot import compact, failed
from partyline.screen_window_click import BUDGET, INPUT_VERSION
from partyline.screen_window_marks import NAME, THUMB_EDGE, THUMB_PIXELS
from partyline.screen_window_snapshot import image_tokens
from tests.test_window_click_server import ClickFixture
from tests.test_window_snapshot import picture

ELEMENTS = [{"id": "win", "control_type": "Window", "name": "Editor"},
            {"id": "save", "parent": "win", "control_type": "Button", "name": "Save", "actions": ["invoke"],
             "bounds": [120, 90, 180, 110]}]
MARKS = [{"n": 1, "id": "e1", "role": "Button", "name": "Save", "box": [20, 40, 80, 60]}]


def node(ident, name, bounds=(120, 90, 180, 110), actions=("invoke",)):
    return SimpleNamespace(id=ident, name=name, actions=actions, bounds=bounds, flags=(), type="Button",
                           cached={})


class PointFixture(ClickFixture):
    """The helper as a fake: it answers point input, element actions and reads and records what it got."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.device["windows"] = INPUT_VERSION
        self.points, self.action_answer, self.reads = [], {"status": "completed"}, []
        self.answer["marks"] = MARKS

    async def receive(self, message):
        if message["type"] == "window_point":
            self.sent.append(message)
            self.points.append(message)
            self.hub.elements.receive(self.device, {"type": "window_element_result",
                                                    "request_id": message["request_id"], **self.click_answer})
            return
        if message["type"] == "window_element_action":
            self.sent.append(message)
            answer = {"request_id": message["request_id"], **self.action_answer}
            self.hub.elements.receive(self.device, answer)
            return
        if message["type"] == "read_window_elements":
            self.sent.append(message)
            self.reads.append(message)
            self.hub.elements.receive(self.device, {
                "request_id": message["request_id"], "status": "completed", "snapshot_id": "t",
                "elements": ELEMENTS})
            return
        await super().receive(message)

    async def call(self, operation, ident="a", **body):
        line = self.db.get_attachment(ident)["conv_id"]
        return await self.client.post(f"/api/conversations/{line}/screen-control/window-{operation}",
                                      json=body, headers=self.machine(ident))

    async def ready(self):
        await self.grant("a")
        self.assertEqual(200, (await self.read("a")).status_code)
        tree = self.hub.elements.snapshots["g1"]
        self.save = next(ident for ident, item in tree.nodes.items() if item.name == "Save")
        self.reads.clear()
        self.assertEqual(200, (await self.shot("a")).status_code)

    def images(self):
        return [item for item in self.requests if item["type"] == "snapshot_window"]


class OperationTests(PointFixture, unittest.IsolatedAsyncioTestCase):
    async def test_scroll_goes_to_the_helper_with_its_geometry_converted_point(self):
        await self.ready()
        response = await self.call("scroll", snapshot="s1", x=100, y=100, dx=0, dy=-3)
        self.assertEqual(200, response.status_code, response.text)
        sent = self.points[0]
        self.assertEqual(("scroll", "s1", [200, 150], 0, -3, "g1"),
                         (sent["op"], sent["snapshot"], sent["screen"], sent["dx"], sent["dy"],
                          sent["grant_id"]))
        self.assertEqual(BUDGET, sent["budget"])  # the click's own start deadline

    async def test_drag_converts_both_ends_with_the_snapshots_geometry(self):
        await self.ready()
        ends = {"from": {"x": 10, "y": 40}, "to": {"x": 300, "y": 200}}
        response = await self.call("drag", snapshot="s1", **ends)
        self.assertEqual(200, response.status_code, response.text)
        sent = self.points[0]
        self.assertEqual(("drag", [110, 90], [400, 250]), (sent["op"], sent["screen"], sent["screen2"]))

    async def test_type_and_key_name_no_point_and_their_text_is_never_logged(self):
        await self.ready()
        self.assertEqual(200, (await self.call("type", text="hunter2 secret")).status_code)
        self.assertEqual(200, (await self.call("key", keys="ctrl+a")).status_code)
        self.assertEqual(200, (await self.call("key", keys="x")).status_code)
        self.assertEqual(("type", "hunter2 secret"), (self.points[0]["op"], self.points[0]["text"]))
        self.assertEqual("ctrl+a", self.points[1]["keys"])
        logged = json.dumps(self.audit())
        self.assertNotIn("hunter2", logged)
        typed = [row for row in self.audit() if row["operation"] == "screen_window_type"][0]
        self.assertEqual(14, typed["characters"])
        self.assertEqual({"characters": 1}, {k: v for k, v in self.audit()[-1].items() if k == "characters"})

    async def test_every_point_refusal_of_click_holds_for_scroll_and_drag(self):
        await self.ready()
        outside = await self.call("scroll", snapshot="s1", x=1, y=1, dy=1)  # the frame, not the client
        self.assertEqual((200, "failed", "outside"), (outside.status_code, outside.json()["status"],
                                                      outside.json()["reason"]))
        self.assertIn("client area", outside.json()["error"])
        off = await self.call("scroll", snapshot="s1", x=400, y=10, dy=1)
        unknown = await self.call("scroll", snapshot="nope", x=100, y=100, dy=1)
        one_end_bad = await self.call("drag", snapshot="s1", **{"from": {"x": 100, "y": 100},
                                                                "to": {"x": 1, "y": 1}})
        for refused, reason in ((off, "outside"), (unknown, "stale"), (one_end_bad, "outside")):
            body = refused.json()
            self.assertEqual(("failed", reason), (body["status"], body["reason"]))
            shot = body["screenshot"]  # each has the picture; none repeats it
            self.assertTrue(shot.get("marks") == MARKS or shot.get("marks_unchanged"), shot)
            self.assertTrue(shot["file"]["id"] and shot["snapshot"])
        self.assertEqual([], self.points)

    async def test_an_old_helper_cannot_scroll_drag_type_or_key_and_still_clicks(self):
        await self.ready()
        self.device["windows"] = 3
        for operation, body in (("scroll", {"snapshot": "s1", "x": 100, "y": 100, "dy": 1}),
                                ("type", {"text": "a"}), ("key", {"keys": "enter"})):
            response = await self.call(operation, **body)
            self.assertEqual(409, response.status_code)
            self.assertIn("update the Partyline helper", response.json()["detail"])
        self.assertEqual(200, (await self.click()).status_code)
        self.assertEqual([], self.points)

    async def test_blocked_combos_and_bad_arguments_never_reach_the_helper(self):
        await self.ready()
        for keys in ("ctrl+alt+delete", "meta+l", "win+l", "ctrl+c", "ctrl+v", "shift+insert", "alt+f4",
                     "ctrl",
                     "ctrl+ctrl+a", "nonsense"):
            with self.subTest(keys=keys):
                self.assertEqual(422, (await self.call("key", keys=keys)).status_code)
        for text in ("", "a" * 501, "bell\x07", "nul\x00"):
            with self.subTest(text=text):
                self.assertEqual(422, (await self.call("type", text=text)).status_code)
        for body in ({"dx": 0, "dy": 0}, {"dx": 51}, {"dy": 1, "extra": 1}):
            with self.subTest(body=body):
                response = await self.call("scroll", snapshot="s1", x=100, y=100, **body)
                self.assertEqual(422, response.status_code)
        half = await self.call("drag", snapshot="s1", **{"from": {"x": 1}, "to": {"x": 1, "y": 1}})
        self.assertEqual(422, half.status_code)
        self.assertEqual([], self.points)
        self.assertEqual(200, (await self.call("type", text="line one\n\tindent")).status_code)

    async def test_a_peer_without_the_line_is_refused_like_the_click(self):
        await self.ready()
        refused = await self.call("scroll", ident="b", snapshot="s1", x=100, y=100, dy=1)
        self.assertEqual(403, refused.status_code)
        self.assertEqual(403, (await self.call("type", ident="b", text="a")).status_code)
        self.assertEqual(403, (await self.call("type", ident="b", text="a")).status_code)


class FailurePictureTests(PointFixture, unittest.IsolatedAsyncioTestCase):
    def fail(self, **answer):
        self.click_answer = {"status": "failed", **answer}

    async def test_a_covered_point_comes_back_with_a_marked_thumb_and_no_second_call(self):
        await self.ready()
        before = len(self.images())
        self.fail(error="another window is on top at that point; no click was sent", reason="covered")
        body = (await self.call("scroll", snapshot="s1", x=100, y=100, dy=1)).json()
        self.assertEqual("failed", body["status"])
        shot = body["screenshot"]
        self.assertEqual(MARKS, shot["marks"])
        self.assertTrue(shot["snapshot"] and shot["file"]["id"])
        taken = self.images()[before:]
        self.assertEqual(1, len(taken))  # the one picture: marked, in the thumb tier, of the granted window
        self.assertEqual(({"edge": THUMB_EDGE, "pixels": THUMB_PIXELS}, True, "g1"),
                         (taken[0]["fit"], taken[0]["overlay"], taken[0]["grant_id"]))
        self.assertEqual(1, len(self.reads))  # the tree was read fresh so the boxes are true

    async def test_each_point_operation_attaches_the_picture_on_a_stale_snapshot(self):
        await self.ready()
        self.fail(error="stale", reason="stale")
        for operation, body in (("scroll", {"snapshot": "s1", "x": 100, "y": 100, "dy": 1}),
                                ("drag", {"snapshot": "s1", "from": {"x": 10, "y": 40},
                                          "to": {"x": 30, "y": 60}}),
                                ("click", {"snapshot": "s1", "x": 100, "y": 100})):
            with self.subTest(operation=operation):
                self.assertIn("screenshot", (await self.call(operation, **body)).json())

    async def test_failures_a_picture_cannot_explain_carry_none(self):
        await self.ready()
        before = len(self.images())
        for answer in ({"error": "consent revoked"},
                       {"error": "the person declined mouse and keyboard input"},
                       {"error": "that window is never clickable (terminal)"}, {"error": "window closed"}):
            self.fail(**answer)
            self.assertNotIn("screenshot", (await self.call("type", text="a")).json())
        self.assertEqual(before, len(self.images()))

    async def test_a_success_has_no_image_unless_asked_and_the_unconfirmed_has_none(self):
        await self.ready()
        before = len(self.images())
        self.click_answer = {"status": "completed", "route": "cdp", "settle": "quiet"}
        body = (await self.call("scroll", snapshot="s1", x=100, y=100, dy=1)).json()
        self.assertTrue(not {"screenshot", "after"} & set(body))
        self.assertEqual(before, len(self.images()))
        asked = (await self.call("scroll", snapshot="s1", x=100, y=100, dy=1, capture="thumb")).json()
        self.assertIn("after", asked)
        self.assertNotIn("screenshot", asked)
        self.click_answer = {"status": "unconfirmed", "error": "the click did not finish in time"}
        self.assertFalse({"screenshot", "after"} & set((await self.call("type", text="a")).json()))

    async def test_a_page_that_never_settled_carries_a_picture_though_the_input_went_through(self):
        await self.ready()
        self.click_answer = {"status": "completed", "route": "cdp", "settle": "deadline"}
        result = (await self.call("scroll", snapshot="s1", x=100, y=100, dy=1)).json()
        self.assertIn("landing_thumb", result)
        self.assertNotIn("screenshot", result)

    async def test_a_caller_without_read_access_gets_the_failure_without_a_picture(self):
        await self.ready()
        self.fail(error="stale", reason="stale")
        before = len(self.images())
        with patch("partyline.screen_failure_snapshot.deny_unless", side_effect=HTTPException(403, "read")):
            body = (await self.call("scroll", snapshot="s1", x=100, y=100, dy=1)).json()
        self.assertEqual(("failed", False), (body["status"], "screenshot" in body))
        self.assertEqual(before, len(self.images()))

    async def test_a_capture_that_fails_leaves_the_failure_with_the_reason(self):
        await self.ready()
        self.fail(error="stale", reason="stale")
        self.answer.update(ok=False, error="the window is minimised")
        body = (await self.call("scroll", snapshot="s1", x=100, y=100, dy=1)).json()
        self.assertEqual("failed", body["status"])
        self.assertIn("minimised", body["screenshot"]["error"])

    def test_only_failures_a_picture_explains_count(self):
        self.assertTrue(failed({"status": "failed", "reason": "covered"}))
        self.assertTrue(failed({"status": "failed", "error": "element is covered or outside the viewport"}))
        self.assertTrue(failed({"status": "failed", "error": "stale or unknown element"}))
        self.assertFalse(failed({"status": "failed", "error": "revoked"}))
        self.assertFalse(failed({"status": "failed", "error": "stale", "grant_ended": True}))
        self.assertFalse(failed({"status": "completed", "settle": "quiet"}))
        self.assertTrue(failed({"status": "completed", "settle": "deadline"}))
        picture = {"variants": {"full": 1}, "width": 3}
        self.assertEqual(picture, compact(picture))


class ElementActionPictureTests(PointFixture, unittest.IsolatedAsyncioTestCase):
    async def action(self, **extra):
        return (await self.client.post(
            "/api/conversations/alpha/screen-control/element-action",
            json={"element_id": self.save, "action": "invoke", **extra}, headers=self.machine("a"))).json()

    async def test_a_failed_action_carries_the_marked_thumb(self):
        await self.ready()
        self.action_answer = {"status": "failed", "error": "element is covered or outside the viewport"}
        body = await self.action()
        self.assertEqual(MARKS, body["screenshot"]["marks"])
        self.assertTrue(body["screenshot"]["snapshot"])

    async def test_a_failure_that_is_not_visual_and_a_plain_success_carry_none(self):
        await self.ready()
        before = len(self.images())
        self.action_answer = {"status": "failed", "error": "audit unavailable"}
        self.assertNotIn("screenshot", await self.action())
        self.action_answer = {"status": "completed", "source": "cdp", "settle": "quiet"}
        self.assertNotIn("screenshot", await self.action())
        self.assertEqual(before, len(self.images()))

    async def test_then_snapshot_alone_returns_a_picture_and_reads_no_tree(self):
        await self.ready()
        self.action_answer = {"status": "completed", "source": "cdp", "settle": "quiet"}
        before = len(self.images())
        reads = len(self.reads)
        body = await self.action(then={"snapshot": True})
        self.assertTrue(body["screenshot"]["snapshot"])
        self.assertNotIn("after", body)
        self.assertEqual(len(self.reads), reads)
        self.assertEqual(before + 1, len(self.images()))
        self.assertNotIn("marks", body["screenshot"])  # no tree was read, so no marks to claim

    async def test_a_default_then_answers_with_what_changed_only(self):
        await self.ready()
        self.action_answer = {"status": "completed", "source": "cdp", "settle": "quiet"}
        body = await self.action(then={})
        self.assertNotIn("screenshot", body)
        for key in ("source", "snapshot_age_seconds", "snapshot_event_counter", "window_title", "nodes"):
            self.assertNotIn(key, body["after"])
        self.assertIn("diff", body["after"])

    async def test_an_explicit_then_read_is_left_whole(self):
        await self.ready()
        self.action_answer = {"status": "completed", "source": "cdp", "settle": "quiet"}
        body = await self.action(then={"query": "x"})
        self.assertIn("snapshot_age_seconds", body["after"])


class ThumbBudgetTests(PointFixture, unittest.IsolatedAsyncioTestCase):
    async def marked(self, **params):
        return (await self.client.post("/api/conversations/alpha/screen-window-snapshot",
                                       params={"marks": "true", **params}, headers=self.machine("a"))).json()

    async def test_a_marked_snapshot_asks_for_the_thumb_budget_and_states_it(self):
        await self.grant("a")
        self.answer.update(width=900, height=700)
        self.image = picture(900, 700)
        body = await self.marked()
        self.assertEqual({"edge": THUMB_EDGE, "pixels": THUMB_PIXELS}, self.requests[0]["fit"])
        self.assertEqual({"tier", "max_edge", "max_pixels", "image_tokens"}, set(body["budget"]))
        self.assertLessEqual(body["budget"]["image_tokens"], 1000)
        self.assertNotIn("full", body["variants"])

    def test_the_budget_never_exceeds_a_thousand_tokens_at_any_shape(self):
        for width, height in ((1000, 700), (700, 1000), (1000, 1000 * 700 // 1000), (1000, 562), (840, 833)):
            scale = min(1, THUMB_EDGE / max(width, height), (THUMB_PIXELS / (width * height)) ** 0.5)
            self.assertLessEqual(image_tokens(round(width * scale), round(height * scale)), 1000)

    async def test_full_tier_and_plain_snapshots_keep_the_windows_own_size(self):
        await self.grant("a")
        await self.marked(tier="full")
        self.assertNotIn("fit", self.requests[0])
        await self.shot("a")
        self.assertNotIn("fit", self.requests[1])

    async def test_an_unchanged_window_answers_with_the_previous_reference(self):
        await self.ready()
        first = (await self.shot("a")).json()
        again = (await self.shot("a")).json()
        self.assertTrue(again["unchanged"])
        self.assertEqual(first["file"]["id"], again["file"]["id"])
        self.assertNotIn("variants", again)
        self.assertEqual("s1", again["snapshot"])
        self.assertEqual(set(again) & {"urls", "variants", "use"}, {"use"})

    async def test_unchanged_marks_are_sent_once(self):
        await self.ready()
        first = await self.marked()
        self.assertEqual(MARKS, first["marks"])
        again = await self.marked()
        self.assertTrue(again["unchanged"] and again["marks_unchanged"])
        self.assertNotIn("marks", again)
        self.hub.elements.snapshots["g1"].nodes[self.save].name = "Saved"
        self.answer["marks"] = [{**MARKS[0], "name": "Saved"}]
        changed = await self.marked()
        self.assertEqual("Saved", changed["marks"][0]["name"])


class MarkFormTests(unittest.TestCase):
    def test_marks_are_compact_visible_and_actionable_with_a_short_name_and_a_cap(self):
        from partyline.screen_window_marks import MAX_MARKS, mark_inputs
        nodes = {str(i): node(str(i), "N" * 90, bounds=(0, 0, 9, 9)) for i in range(MAX_MARKS + 20)}
        nodes["off"] = node("off", "Hidden")
        nodes["off"].flags = ("off",)
        nodes["plain"] = node("plain", "Text", actions=("press", "scroll_into_view"))
        marks = mark_inputs(SimpleNamespace(order=list(nodes), nodes=nodes))
        self.assertEqual(MAX_MARKS, len(marks))
        self.assertEqual({"n", "id", "role", "name", "screen"}, set(marks[0]))
        self.assertEqual(NAME, len(marks[0]["name"]))
        self.assertEqual(list(range(1, MAX_MARKS + 1)), [m["n"] for m in marks])


class ToolTests(unittest.TestCase):
    STATE = {"dynamic_screen_tools": True, "screen_windows": True}

    def test_the_four_tools_are_listed_with_window_grants_only_and_carry_the_guidance(self):
        names = {tool["name"]: tool for tool in tools_control.tool_list(self.STATE)}
        self.assertEqual(tools_point.NAMES, {name for name in names if name in tools_point.NAMES})
        for name in tools_point.NAMES:
            tool = names[name]
            self.assertNotIn("frame", tool["inputSchema"]["properties"])
            self.assertIn("screen_element_action", tool["description"])
            self.assertIn("Never click or type with page scripts", tool["description"])
        self.assertEqual(["snapshot", "from", "to"], names["screen_window_drag"]["inputSchema"]["required"])
        self.assertEqual(["text"], names["screen_window_type"]["inputSchema"]["required"])
        read_only = {tool["name"] for tool in tools_control.tool_list({"dynamic_screen_tools": True,
                                                                      "screen_read": True})}
        self.assertFalse(tools_point.NAMES & read_only)

    def test_calls_go_to_their_own_route_with_the_click_timeout(self):
        calls = []
        client = SimpleNamespace(home="line", request=lambda *args, **kw: calls.append((args, kw)) or {})
        for name, args in (("screen_window_scroll", {"snapshot": "s", "x": 1, "y": 2, "dy": 1}),
                           ("screen_window_drag", {"snapshot": "s", "from": {"x": 1, "y": 2},
                                                   "to": {"x": 3, "y": 4}}),
                           ("screen_window_type", {"text": "a"}), ("screen_window_key", {"keys": "enter"})):
            tools_control.call(client, name, args, self.STATE)
        self.assertEqual(["/api/conversations/line/screen-control/window-" + op
                          for op in ("scroll", "drag", "type", "key")], [call[0][1] for call in calls])
        self.assertTrue(all(call[1]["timeout"] == tools_control.WINDOW_CLICK_TIMEOUT for call in calls))

    def test_the_guidance_prefers_elements_and_names_the_fallback_without_script_clicks(self):
        from partyline.mcp import tools_screen
        action = next(t for t in tools_control.tool_list(self.STATE) if t["name"] == "screen_element_action")
        for text in (action["description"], tools_screen.ELEMENTS_NOTE, tools_screen.WINDOW_SNAPSHOT_NOTE):
            self.assertIn("screen_element", text)
        self.assertIn("screenshot", action["description"])
        self.assertIn("never script clicks", action["description"])
        self.assertIn("at most 60", json.dumps(tools_screen.screen_window_snapshot_tool()))
        self.assertIn("930", tools_screen.WINDOW_SNAPSHOT_NOTE)


if __name__ == "__main__":
    unittest.main()
