"""screen_window_click on the server: snapshot geometry, conversion, refusals, routing, audit, marks."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from partyline.mcp import catalog, tools_control, tools_screen

from partyline.point_geometry import GeometryError, clean, locate, to_image, to_screen
from partyline.screen_window_click import BUDGET, DISPATCH, MARGIN, STALE, WAIT
from partyline_helper import window_click as helper
from partyline.screen_window_marks import MAX_MARKS, Geometries, clean_marks, mark_inputs
from tests.test_window_snapshot import SnapshotFixture

GEOMETRY = {"rect": [100, 50, 500, 350], "size": [400, 300], "dpi": 96,
            "regions": [[108, 80, 492, 342]]}


def node(ident, name="", actions=("invoke",), bounds=None, flags=(), viewport=None):
    return SimpleNamespace(id=ident, name=name, actions=actions, bounds=bounds, flags=flags, type="Button",
                           cached={"viewport_bounds": viewport} if viewport else {})


class ClickFixture(SnapshotFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.device["windows"] = 3
        self.clicks, self.click_answer = [], {"status": "completed", "route": "cursor", "settle": "quiet"}
        self.answer.update(snapshot_id="s1", geometry=GEOMETRY, width=400, height=300)

    async def receive(self, message):
        if message["type"] == "window_click":
            self.sent.append(message)
            self.clicks.append(message)
            self.hub.elements.receive(self.device, {"type": "window_element_result",
                                                    "request_id": message["request_id"], **self.click_answer})
            return
        if message["type"] == "read_window_elements":  # the fresh read behind a failure's marked picture
            self.sent.append(message)
            self.hub.elements.receive(self.device, {
                "request_id": message["request_id"], "status": "completed", "snapshot_id": "t",
                "elements": [{"id": "win", "control_type": "Window", "name": "Editor"}]})
            return
        await super().receive(message)

    async def click(self, ident="a", **body):
        line = self.db.get_attachment(ident)["conv_id"]
        body = {"snapshot": "s1", "x": 100, "y": 100, **body}
        return await self.client.post(f"/api/conversations/{line}/screen-control/window-click",
                                      json=body, headers=self.machine(ident))

    def audit(self):
        return [json.loads(row["entry"]) for row in self.db._exec(
            "SELECT entry FROM screen_control_audit ORDER BY id").fetchall()
            if row["entry"].startswith("{")]


class WindowClickTests(ClickFixture, unittest.IsolatedAsyncioTestCase):
    async def snapshot(self):
        body = (await self.shot("a")).json()
        self.assertEqual("s1", body["snapshot"])
        return body

    async def test_a_snapshot_names_its_pixels_and_a_click_is_converted_with_its_geometry(self):
        await self.grant("a")
        body = await self.snapshot()
        self.assertIn("pixels of this image", body["coordinates"])
        response = await self.click(x=100, y=100)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("completed", response.json()["status"])
        sent = self.clicks[0]
        self.assertEqual(("alpha", "Alpha"), (sent["line"], sent["line_name"]))
        self.assertEqual(("g1", "s1", [200, 150], 100, 100, "left", 1),
                         (sent["grant_id"], sent["snapshot"], sent["screen"], sent["x"], sent["y"],
                          sent["button"], sent["clicks"]))

    async def test_the_helper_gets_a_start_deadline_and_the_server_waits_longer_than_it_can_take(self):
        await self.grant("a")
        await self.snapshot()
        waits = []
        original = self.hub.elements.exchange

        async def spying(*args, **kwargs):
            waits.append(kwargs["wait"])
            return await original(*args, **kwargs)
        with patch.object(self.hub.elements, "exchange", spying):
            await self.click()
        self.assertEqual([WAIT], waits)
        self.assertEqual(BUDGET, self.clicks[0]["budget"])
        self.assertNotIn("wait", self.clicks[0])  # the server's own timeout is not a field of the request
        # a click starts within BUDGET of arriving and takes at most DISPATCH more; the server outwaits both
        self.assertGreaterEqual(WAIT, BUDGET + helper.TIMEOUT + MARGIN)
        self.assertGreaterEqual(DISPATCH, helper.TIMEOUT)
        self.assertGreater(WAIT, 35)

    async def test_the_exchange_wait_is_the_deadline_used_and_other_calls_keep_35_seconds(self):
        import inspect
        await self.grant("a")
        await self.snapshot()
        seen, real = [], asyncio.timeout

        def recording(delay):
            seen.append(delay)
            return real(delay)
        with patch("partyline.screen_elements.asyncio.timeout", recording):
            await self.click()
        self.assertEqual([WAIT], seen)
        self.assertEqual(35, inspect.signature(self.hub.elements.exchange).parameters["wait"].default)

    async def test_scale_and_dpi_convert_the_pixel_centre(self):
        await self.grant("a")
        self.answer["geometry"] = {"rect": [100, 50, 500, 350], "size": [800, 600], "dpi": 144,
                                   "regions": [[108, 80, 492, 342]]}
        await self.snapshot()
        await self.click(x=300, y=200, button="right", clicks=2)
        self.assertEqual([250, 150], self.clicks[0]["screen"])  # 100 + 300.5 / 2, 50 + 200.5 / 2
        self.assertEqual(("right", 2), (self.clicks[0]["button"], self.clicks[0]["clicks"]))

    async def test_points_outside_the_image_or_the_client_area_are_refused_without_a_request(self):
        await self.grant("a")
        await self.snapshot()
        for x, y, text in ((400, 10, "outside the snapshot image"), (5, 100, "client area"),
                           (200, 5, "client area"), (10, 300, "outside the snapshot image")):
            with self.subTest(x=x, y=y):
                response = await self.click(x=x, y=y)
                body = response.json()  # a refusal is an answer, so it can carry the picture to retry from
                self.assertEqual((200, "failed", "outside"),
                                 (response.status_code, body["status"], body["reason"]))
                self.assertIn(text, body["error"])
                self.assertIn("file", body["screenshot"])
        self.assertEqual([], self.clicks)

    async def test_an_unknown_snapshot_or_another_grants_snapshot_is_refused(self):
        await self.grant("a")
        await self.snapshot()
        response = await self.click(snapshot="nope")
        body = response.json()
        self.assertEqual((200, "failed", "stale", STALE),
                         (response.status_code, body["status"], body["reason"], body["error"]))
        self.assertEqual("g1", self.sent[-1]["grant_id"])  # the picture is of the granted window alone
        self.assertEqual("snapshot_window", self.sent[-1]["type"])
        self.assertTrue(body["screenshot"]["marks"] is not None and body["screenshot"]["file"]["id"])
        self.assertIn("take a fresh screen_window_snapshot", STALE)
        await self.hub.window_grants.revoke("g1")  # the grant ends: its snapshots go with it
        self.assertIsNone(self.hub.snapshots.geometry.get("g1", "s1"))
        await self.grant("a", grant_id="g2", hwnd=11)
        other = (await self.click()).json()  # s1 belonged to g1, not g2
        self.assertEqual(("failed", "stale"), (other["status"], other["reason"]))
        self.assertEqual([], self.clicks)

    async def test_a_helper_that_cannot_click_is_told_to_update(self):
        await self.grant("a")
        await self.snapshot()
        self.device["windows"] = 2
        response = await self.click()
        self.assertEqual(409, response.status_code)
        self.assertIn("update the Partyline helper", response.json()["detail"])
        self.assertEqual([], self.clicks)

    async def test_another_line_cannot_click_a_window_it_was_not_given(self):
        await self.grant("a")
        await self.snapshot()
        self.assertEqual(403, (await self.click("b")).status_code)
        self.assertEqual([], self.clicks)

    async def test_the_click_is_audited_before_and_after_with_route_point_and_result(self):
        await self.grant("a")
        await self.snapshot()
        await self.click(x=100, y=100)
        rows = [row for row in self.audit() if row.get("operation") == "screen_window_click"]
        self.assertEqual(["pending", "cursor"], [row["route"] for row in rows])
        self.assertEqual(["requested", "completed"], [row["result"] for row in rows])
        last = rows[-1]
        self.assertEqual(("g1", "a", [100, 100], [200, 150]),
                         (last["grant"], last["process"], last["point"], last["screen"]))
        self.assertNotIn("data", json.dumps(rows))  # metadata only, never pixels

    async def test_a_helper_refusal_is_returned_and_audited(self):
        await self.grant("a")
        await self.snapshot()
        self.click_answer = {"status": "failed", "error": "another window is on top"}
        response = await self.click()
        self.assertEqual("failed", response.json()["status"])
        self.assertEqual("failed", self.audit()[-1]["result"])

    async def test_a_helper_that_does_not_answer_is_unconfirmed_not_retried(self):
        await self.grant("a")
        await self.snapshot()

        async def silent(*args, **kwargs):
            raise TimeoutError
        with patch.object(self.hub.elements, "exchange", silent):
            response = await self.click()
        self.assertEqual("unconfirmed", response.json()["status"])
        self.assertIn("may have run", response.json()["note"])

    async def test_a_thumb_snapshot_is_taken_after_the_click_when_asked(self):
        await self.grant("a")
        await self.snapshot()
        response = await self.click(capture="thumb")
        after = response.json()["after"]
        self.assertTrue(after["file"]["id"])
        self.assertEqual("s1", after["snapshot"])
        self.assertEqual(3, len(self.requests))  # unchanged after also gets the landing crop

    async def test_an_older_helper_cannot_pass_an_unmarked_full_image_off_as_a_landing_thumb(self):
        await self.grant("a")
        await self.snapshot()
        self.click_answer["settle"] = "unchanged"
        result = (await self.click()).json()
        self.assertIn("update the Partyline helper", result["landing_thumb"]["error"])
        self.assertNotIn("file", result["landing_thumb"])

    async def test_a_click_forgets_the_element_tree_so_the_next_read_is_fresh(self):
        await self.grant("a")
        await self.snapshot()
        self.hub.elements.snapshots["g1"] = SimpleNamespace(order=[], nodes={})
        await self.click()
        self.assertNotIn("g1", self.hub.elements.snapshots)

    async def test_a_marked_snapshot_asks_for_boxes_and_lists_what_the_helper_drew(self):
        await self.grant("a")
        self.hub.elements.snapshots["g1"] = SimpleNamespace(
            order=["e1", "e2"], nodes={"e1": node("e1", "Save", bounds=(120, 90, 180, 110)),
                                       "e2": node("e2", "Page", viewport=(0, 0, 50, 20))})
        self.answer["marks"] = [{"n": 1, "id": "e1", "name": "Save", "box": [20, 40, 80, 60]},
                                {"n": 2, "id": "e2", "name": "Page", "box": [1, 2, "x", 4]}, "junk"]
        body = (await self.client.post(
            "/api/conversations/alpha/screen-window-snapshot", params={"marks": "true"},
            headers=self.machine("a"))).json()
        request = self.requests[0]
        self.assertTrue(request["overlay"])
        self.assertEqual([{"n": 1, "id": "e1", "role": "Button", "name": "Save",
                           "screen": [120, 90, 180, 110]},
                          {"n": 2, "id": "e2", "role": "Button", "name": "Page", "viewport": [0, 0, 50, 20]}],
                         request["marks"])
        self.assertEqual([{"n": 1, "id": "e1", "role": "", "name": "Save", "box": [20, 40, 80, 60]}],
                         body["marks"])

    async def test_a_marked_snapshot_without_a_read_says_so_and_still_gets_the_grid(self):
        await self.grant("a")
        body = (await self.client.post("/api/conversations/alpha/screen-window-snapshot",
                                       params={"marks": "true"}, headers=self.machine("a"))).json()
        self.assertEqual(([], True), (body["marks"], self.requests[0]["overlay"]))
        self.assertIn("read it first", body["marks_note"])
        plain = (await self.shot("a")).json()
        self.assertNotIn("marks", plain)
        self.assertNotIn("overlay", self.requests[-1])


class ToolTests(unittest.TestCase):
    def test_the_tool_is_listed_with_window_grants_only_and_validates_its_arguments(self):
        shown = {"dynamic_screen_tools": True, "screen_windows": True}
        tool = next(item for item in tools_control.tool_list(shown) if item["name"] == "screen_window_click")
        properties = tool["inputSchema"]["properties"]
        self.assertEqual(["snapshot", "x", "y"], tool["inputSchema"]["required"])
        self.assertEqual(["left", "right"], properties["button"]["enum"])
        self.assertEqual([1, 2], properties["clicks"]["enum"])
        self.assertNotIn("frame", properties)
        self.assertIn("Last resort", tool["description"])
        self.assertIn("Never click with page scripts", tool["description"])
        for state in ({"dynamic_screen_tools": True, "screen_read": True},
                      {"dynamic_screen_tools": True, "screen_windows": True, "screen_control": True}):
            names = {item["name"] for item in tools_control.tool_list(state)}
            self.assertEqual("screen_window_click" in names, bool(state.get("screen_windows")))
        self.assertIn("screen_window_click", catalog.SCREEN_CONTROL)
        calls = []
        client = SimpleNamespace(home="line", request=lambda *args, **kw: calls.append((args, kw)) or {})
        args = {"snapshot": "s1", "x": 3, "y": 4, "button": "right", "clicks": 2, "window": "g1"}
        tools_control.call(client, "screen_window_click", args, shown)
        self.assertEqual(("POST", "/api/conversations/line/screen-control/window-click", args), calls[0][0])
        for bad in ({"button": "middle"}, {"clicks": 3}, {"x": -1}, {"extra": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                catalog.validate_arguments(tool["inputSchema"], {**args, **bad}, "")

    def test_a_marked_snapshot_is_asked_for_with_a_query_flag(self):
        calls = []
        client = SimpleNamespace(home="line", request=lambda *args, **kw: calls.append(args) or {})
        tools_screen.call(client, "screen_window_snapshot", {"window": "g1", "marks": True}, {}, "line")
        self.assertEqual("/api/conversations/line/screen-window-snapshot?window=g1&marks=true", calls[0][1])
        tools_screen.call(client, "screen_window_snapshot", {}, {}, "line")
        self.assertEqual("/api/conversations/line/screen-window-snapshot", calls[1][1])


class GeometryTests(unittest.TestCase):
    def test_conversion_is_exact_at_scale_one_and_at_the_edges(self):
        geometry = clean(GEOMETRY)
        self.assertEqual((100, 50), to_screen(geometry, 0, 0))
        self.assertEqual((499, 349), to_screen(geometry, 399, 299))
        self.assertEqual((300.0, 200.0), to_image(geometry, 400, 250))
        self.assertEqual((200, 150), locate(geometry, 100, 100))

    def test_a_bad_point_or_geometry_is_an_error_never_clamped(self):
        geometry = clean(GEOMETRY)
        for x, y in ((-1, 0), (0, 300), (400, 0), (True, 1), (1.5, 1), ("1", 1)):
            with self.subTest(x=x, y=y), self.assertRaises(GeometryError):
                to_screen(geometry, x, y)
        for data in (None, {}, {**GEOMETRY, "rect": [1, 2, 3]}, {**GEOMETRY, "rect": [5, 5, 5, 9]},
                     {**GEOMETRY, "regions": []}, {**GEOMETRY, "size": [0, 5]},
                     {**GEOMETRY, "regions": [[1, 2, 3, "x"]]}, {**GEOMETRY, "rect": [True, 0, 4, 4]}):
            with self.subTest(data=data), self.assertRaises(GeometryError):
                clean(data)
        self.assertEqual(96, clean({**GEOMETRY, "dpi": "high"})["dpi"])

    def test_the_geometry_store_keeps_the_last_few_and_forgets_with_the_grant(self):
        store = Geometries()
        self.assertFalse(store.keep("g", "s", {"bad": 1}))
        self.assertFalse(store.keep("g", "", GEOMETRY))
        for number in range(10):
            self.assertTrue(store.keep("g", f"s{number}", GEOMETRY))
        self.assertIsNone(store.get("g", "s0"))
        self.assertIsNotNone(store.get("g", "s9"))
        store.end("g")
        self.assertIsNone(store.get("g", "s9"))
        store.end("never")


class MarkTests(unittest.TestCase):
    def test_marks_list_only_visible_actionable_elements_in_tree_order(self):
        nodes = {"a": node("a", "Label", actions=("scroll_into_view", "press"), bounds=(0, 0, 9, 9)),
                 "b": node("b", "Go", bounds=(1, 1, 5, 5)),
                 "c": node("c", "Hidden", bounds=(1, 1, 5, 5), flags=("off",)),
                 "d": node("d", "", actions=(), bounds=(1, 1, 5, 5)),
                 "e": node("e", "Nobox"), "f": node("f", "Bad", bounds=(1, 2, 3))}
        tree = SimpleNamespace(order=list(nodes), nodes=nodes)
        self.assertEqual([("b", 1)], [(m["id"], m["n"]) for m in mark_inputs(tree)])
        self.assertEqual({"n": 1, "id": "b", "role": "Button", "name": "Go", "screen": [1, 1, 5, 5]},
                         mark_inputs(tree)[0])
        many = {str(i): node(str(i), "x", bounds=(0, 0, 4, 4)) for i in range(MAX_MARKS + 5)}
        self.assertEqual(MAX_MARKS, len(mark_inputs(SimpleNamespace(order=list(many), nodes=many))))

    def test_helper_marks_are_cut_to_whole_numbers(self):
        self.assertEqual([], clean_marks("nope"))
        self.assertEqual([{"n": 1, "id": "i", "role": "", "name": "n", "box": [1, 2, 3, 4]}],
                         clean_marks([{"n": 1, "id": "i", "name": "n", "box": [1, 2, 3, 4]},
                                      {"n": 2, "box": [1.5, 2, 3, 4]}, {"n": "3", "box": [1, 2, 3, 4]}]))


if __name__ == "__main__":
    unittest.main()
