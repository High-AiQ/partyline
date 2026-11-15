"""Landing evidence, activation ordering and physical pixel mapping, without native input or time waits."""
import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

from partyline.point_geometry import clean, locate
from partyline_helper.landing_thumb import marked
from partyline_helper.point_win32 import Win32Pointer
from partyline_helper.window_grab import GrabError
from partyline_helper.window_snapshot import WindowSnapshots
from tests.test_helper_window_click import ClickFixture
from tests.test_helper_point_input import PointFixture
from tests.test_point_input_server import PointFixture as ServerFixture


class LandingTests(ClickFixture):
    async def test_click_reports_geometry_raw_child_and_foreground_before_restore(self):
        self.pointer.front, self.pointer.under = 50, 11
        result = await self.click()
        self.assertEqual({"snapshot": self.snapshot, "dpi": 96, "dpi_scale": 1.0,
                          "image_scale": [1.0, 1.0], "foreground_before": False,
                          "foreground_after": True, "input_sent": True,
                          "points": [{"snapshot_point": [100, 100], "screen_point": [200, 150],
                                      "hwnd": 11, "class": "TestChild", "granted_window": False,
                                      "page_area_child": True, "landed_in": "granted_page"}]},
                         result["landing"])
        self.assertNotIn("Editor", json.dumps(result["landing"]))
        self.assertIn(("restore", 50), self.pointer.calls)

    async def test_raw_child_evidence_keeps_the_original_top_level_floor_guard(self):
        self.pointer.under = 12
        self.pointer.root = lambda hwnd: 10 if hwnd == 12 else hwnd
        self.pointer.image_name = lambda hwnd: "pwsh.exe" if hwnd == 10 else "editor.exe"
        result = await self.click()
        self.assertEqual("failed", result["status"])
        self.assertEqual(12, result["landing"]["points"][0]["hwnd"])
        self.assertFalse(result["landing"]["input_sent"])
        self.assertEqual([], self.sends())

    async def test_a_covered_point_identifies_the_other_window_without_sending(self):
        self.pointer.under = 99
        result = await self.click()
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["landing"]["input_sent"])
        self.assertEqual(99, result["landing"]["points"][0]["hwnd"])
        self.assertFalse(result["landing"]["points"][0]["granted_window"])

    async def test_activation_is_confirmed_before_the_page_click_and_is_never_the_click(self):
        self.pointer.front = 50
        original = self.pointer.send

        def send(*args):
            self.assertEqual(10, self.pointer.front)  # a background click would only activate this fake
            self.assertIn(("bring_forward", 10), self.pointer.calls)
            self.assertEqual("foreground", self.pointer.calls[-1])
            return original(*args)
        self.pointer.send = send
        self.assertEqual("completed", (await self.click())["status"])
        self.assertEqual(1, len(self.sends()))

    async def test_an_already_foreground_window_gets_exactly_one_page_click(self):
        result = await self.click()
        self.assertTrue(result["landing"]["foreground_before"])
        self.assertTrue(result["landing"]["foreground_after"])
        self.assertFalse(result["target_came_forward"])
        self.assertEqual(1, len(self.sends()))
        self.assertNotIn(("bring_forward", 10), self.pointer.calls)

    async def test_failed_activation_does_not_send_an_activating_click(self):
        self.pointer.front = 50
        self.pointer.bring_forward = Mock(return_value=False)
        result = await self.click()
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["landing"]["input_sent"])
        self.assertEqual([], self.sends())

    async def test_cdp_observes_without_activating_or_moving_the_mouse(self):
        self.access.grant["process"] = "chrome.exe"
        self.shares.chrome.page.return_value = self.page
        self.pointer.front = 50
        result = await self.click()
        self.assertEqual("cdp", result["route"])
        self.assertEqual((False, False, True), tuple(result["landing"][key] for key in
                                                   ("foreground_before", "foreground_after", "input_sent")))
        self.assertFalse(any(isinstance(c, tuple) and c[0] in ("move", "bring_forward", "send")
                             for c in self.pointer.calls))

    async def test_mapping_uses_the_named_image_even_when_a_later_snapshot_has_a_different_size(self):
        original = self.snapshot
        image = Image.new("RGB", (200, 150))
        image.info.update(rect=(100, 50, 500, 350), regions=[(108, 80, 492, 342)], dpi=144)
        WindowSnapshots.remember(self.entry, self.access.grant, image, self.access.gate.generation)
        result = await self.click()
        self.assertEqual(original, result["landing"]["snapshot"])
        self.assertEqual((200, 150), self.pointer.sent_at)
        self.access.gate.invalidate()
        self.access.gate.grant()
        self.assertEqual("stale", (await self.click())["reason"])
        self.assertEqual(1, len(self.sends()))

    async def test_the_actual_snapshot_pipeline_makes_a_small_marked_crop_without_new_coordinates(self):
        self.backend.grab = lambda hwnd: Image.new("RGB", (400, 300), (100, 100, 100))
        image = self.backend.grab(10)
        image.info.update(rect=(100, 50, 500, 350), regions=[(108, 80, 492, 342)], dpi=96)
        self.backend.grab = lambda hwnd: image
        self.backend.minimized = lambda hwnd: False
        await self.shares.snapshots.handle(self.entry, {"request_id": "crop", "agent": "alice",
                                                       "landing": [200, 150]})
        reply = next(item for item in self.socket.sent if isinstance(item, dict)
                     and item.get("request_id") == "crop")
        self.assertEqual((True, 240, 240), (reply["ok"], reply["width"], reply["height"]))
        self.assertNotIn("snapshot_id", reply)
        data = next(item for item in self.socket.sent if isinstance(item, bytes))
        self.assertEqual((220, 0, 40), Image.open(BytesIO(data)).getpixel((100, 100)))


class ParityTests(PointFixture):
    async def test_scroll_and_drag_include_both_named_endpoints_and_keyboard_has_no_point(self):
        self.shares.clicks.pointer = lambda hwnd: self.pointer
        scroll = (await self.point("scroll", dy=1))["landing"]
        drag = (await self.point("drag"))["landing"]
        self.assertEqual([[100, 100]], [p["snapshot_point"] for p in scroll["points"]])
        self.assertEqual([[200, 150], [300, 250]], [p["screen_point"] for p in drag["points"]])
        await self.clicked()
        self.assertEqual([], (await self.point("type", text="a"))["landing"]["points"])


class MappingTests(unittest.TestCase):
    def test_mcp_timeout_covers_the_helper_and_all_three_bounded_pictures(self):
        from partyline.mcp.tools_control import WINDOW_CLICK_TIMEOUT
        from partyline.screen_failure_snapshot import SECONDS
        from partyline.screen_window_click import WAIT
        self.assertGreater(WINDOW_CLICK_TIMEOUT, WAIT + 3 * SECONDS)

    def test_native_hit_test_preserves_the_child_handle_and_reports_its_platform_class(self):
        pointer = Win32Pointer.__new__(Win32Pointer)
        pointer.user = SimpleNamespace(WindowFromPoint=lambda point: 11, GetAncestor=lambda h, kind: 10)
        pointer.scope = SimpleNamespace(window_class=lambda hwnd: "Chrome_RenderWidgetHostHWND")
        self.assertEqual(11, pointer.window_at(-100, -200))
        self.assertEqual(10, pointer.root(11))
        self.assertEqual(0, pointer.root(0))
        self.assertEqual({"hwnd": 11, "class": "Chrome_RenderWidgetHostHWND", "granted_window": False,
                          "page_area_child": True}, pointer.describe(11, 10))
        self.assertTrue(pointer.describe(10, 10)["granted_window"])
        self.assertFalse(pointer.describe(10, 10)["page_area_child"])
        self.assertFalse(pointer.describe(0, 10)["page_area_child"])


    def test_snapshot_to_physical_sendinput_roundtrip_at_each_dpi_on_negative_secondary_monitor(self):
        desktop = (-3840, -1080, 7680, 3240)
        pointer = Win32Pointer.__new__(Win32Pointer)
        metrics = dict(zip((76, 77, 78, 79), desktop, strict=True))
        pointer.user = SimpleNamespace(GetSystemMetrics=metrics.__getitem__)
        for dpi, expected in ((96, (-2330, -142)), (120, (-2227, -40)),
                              (144, (-2125, 62)), (192, (-1919, 267))):
            with self.subTest(dpi=dpi):
                width, height = 800 * dpi // 96, 600 * dpi // 96
                rect = [-2740, -550, -2740 + width, -550 + height]
                geometry = clean({"rect": rect, "size": [800, 600], "dpi": dpi, "regions": [rect]})
                point = locate(geometry, 410, 408)
                self.assertEqual(expected, point)
                absolute = pointer.desktop(*point)
                decoded = tuple(origin + value * size // 65536
                                for origin, value, size in
                                zip(desktop[:2], absolute, desktop[2:], strict=True))
                self.assertEqual(point, decoded)  # the old 65535/(size-1) mapping misses by one
                for pixel in ((0, 0), (799, 599)):
                    point = locate(geometry, *pixel)
                    absolute = pointer.desktop(*point)
                    self.assertEqual(point, tuple(origin + value * size // 65536 for origin, value, size in
                                                  zip(desktop[:2], absolute, desktop[2:], strict=True)))

    def test_crop_marks_the_landing_point_at_the_edge_and_never_includes_outside_pixels(self):
        image = Image.new("RGB", (300, 200), (50, 60, 70))
        image.info.update(rect=(-600, -400, -300, -200))
        crop = marked(image, [-301, -201])
        self.assertEqual((240, 200), crop.size)
        self.assertEqual((220, 0, 40), crop.getpixel((239, 199)))
        self.assertEqual((50, 60, 70), crop.getpixel((10, 10)))
        self.assertEqual({}, crop.info)
        self.assertEqual((50, 60, 70), image.getpixel((299, 199)))
        for point in ([0, 0], [True, 0], None, [1]):
            with self.assertRaises(GrabError):
                marked(image, point)
        image.info.clear()
        with self.assertRaises(GrabError):
            marked(image, [1, 1])


class ServerLandingTests(ServerFixture, unittest.IsolatedAsyncioTestCase):
    async def receive(self, message):
        if message["type"] != "snapshot_window" or "landing" not in message:
            return await super().receive(message)
        from tests.test_window_snapshot import picture
        answer, image = self.answer, self.image
        self.answer = {"ok": True, "mime": "image/webp", "media": True, "landing_marked": True,
                       "width": 240, "height": 240}
        self.image = picture(240, 240)
        try:
            return await super().receive(message)
        finally:
            self.answer, self.image = answer, image

    async def test_repeated_crops_keep_usable_urls_and_do_not_replace_the_full_picture_cache(self):
        await self.ready()
        self.click_answer = {"status": "completed", "settle": "unchanged"}
        first = (await self.click()).json()
        second = (await self.click()).json()
        self.assertTrue(second["landing_thumb"]["unchanged"])
        self.assertIn("slim", second["landing_thumb"]["variants"])
        self.assertEqual(first["landing_thumb"]["file"]["id"], second["landing_thumb"]["file"]["id"])
        self.assertTrue((await self.shot("a")).json()["unchanged"])


    async def test_unchanged_click_scroll_and_drag_always_request_a_crosshair_crop_without_tree_reads(self):
        await self.ready()
        self.click_answer = {"status": "completed", "route": "cursor", "settle": "unchanged",
                             "landing": {"input_sent": True, "points": [{"hwnd": 123}]}}
        for operation, arguments, expected in (
                ("click", {"x": 100, "y": 100}, [200, 150]),
                ("scroll", {"x": 100, "y": 100, "dy": 1}, [200, 150]),
                ("drag", {"from": {"x": 100, "y": 100}, "to": {"x": 200, "y": 200}}, [300, 250])):
            with self.subTest(operation=operation):
                response = (await self.call(operation, snapshot="s1", **arguments)).json()
                self.assertIn("file", response["landing_thumb"])
                self.assertEqual(self.click_answer["landing"], response["landing"])
                self.assertEqual(expected, self.images()[-1]["landing"])
                self.assertNotIn("overlay", self.images()[-1])
                self.assertEqual([], self.reads)

    async def test_no_effect_and_unchanged_after_both_get_the_diagnostic(self):
        await self.ready()
        self.click_answer = {"status": "no_effect"}
        response = (await self.click()).json()
        self.assertIn("landing_thumb", response)
        self.click_answer = {"status": "completed", "settle": "quiet"}
        response = (await self.click(capture="thumb")).json()
        self.assertTrue(response["after"]["unchanged"])
        self.assertIn("landing_thumb", response)

    async def test_diagnostics_still_require_read_permission(self):
        from fastapi import HTTPException
        from unittest.mock import patch
        await self.ready()
        self.click_answer = {"status": "completed", "settle": "unchanged"}
        before = len(self.images())
        with patch("partyline.screen_failure_snapshot.deny_unless", side_effect=HTTPException(403, "read")):
            result = (await self.click()).json()
        self.assertNotIn("landing_thumb", result)
        self.assertEqual(before, len(self.images()))

    async def test_a_server_refusal_has_unknown_landing_fields_and_proves_nothing_was_sent(self):
        await self.ready()
        response = (await self.click(snapshot="unknown")).json()
        self.assertEqual(False, response["landing"]["input_sent"])
        self.assertIsNone(response["landing"]["dpi"])
        self.assertIsNone(response["landing"]["points"][0]["hwnd"])
        self.assertEqual([], self.clicks)
