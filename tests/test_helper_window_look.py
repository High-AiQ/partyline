"""Helper look reads and captures serially; the rendered boxes and text share their source."""
import asyncio
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from partyline_helper.uia_task import WindowTask
from partyline_helper.window_look import check
from tests import test_helper_window_snapshot as snapshot_cases


class HelperLookTests(unittest.IsolatedAsyncioTestCase):
    setUp = snapshot_cases.HelperSnapshotTests.setUp
    asyncTearDown = snapshot_cases.HelperSnapshotTests.asyncTearDown

    def prepare(self, source="uia", size=(800, 600)):
        self.backend.image = Image.new("RGB", size, (30, 90, 200))
        self.backend.image.info.update(rect=(0, 0, *size), regions=[(0, 0, *size)], dpi=96)
        self.access.event_status = lambda: {"event_counter": 4}
        self.raw = [{"id": "plain", "name": "Decoration", "bounds": [100, 100, 200, 200]},
                    {"id": "act", "control_type": "Button", "name": "Save", "actions": ["invoke"],
                     "bounds": [200, 200, 300, 300]}]
        self.part = {"elements": self.raw, "snapshot_id": "tree1", "captured_event_counter": 4}
        self.events = []
        self.worker = WindowTask(SimpleNamespace(window=self.access, chrome=None))
        self.entry["worker"] = self.worker
        async def read(*args):
            self.assertTrue(self.worker.operation_lock.locked())
            self.events.append("read")
            return self.part
        if source == "uia":
            self.access.snapshot = read
        else:
            self.worker.session.chrome = SimpleNamespace(read=read, metadata=lambda access: {}, reasons={})
            self.part["source"] = "cdp"
            self.part["timing"] = {"ax_tree_ms": 3, "cdp_commands": 5,
                                   "total_ms": 100, "ax_nodes": 4, "mapped_nodes": 4}
        grab = type(self.backend).grab
        def capture(hwnd):
            self.assertTrue(self.worker.operation_lock.locked())
            self.events.append("capture")
            return grab(self.backend, hwnd)
        self.backend.grab = capture

    async def ask(self, **extra):
        await self.session.dispatch({"type": "look_window", "request_id": "r1", "grant_id": "g1",
                                     "agent": "alice", "overlay": True,
                                     "fit": {"edge": 1000, "pixels": 700_000}, **extra})
        await asyncio.gather(*self.shares.tasks)
        return await self.socket.next("window_snapshot")

    async def test_fresh_read_then_capture_both_transports_share_generation_and_geometry(self):
        for source in ("uia", "cdp"):
            self.prepare(source)
            reply = await self.ask()
            self.assertTrue(reply["ok"], reply)
            self.assertEqual(["read", "capture"], self.events)
            self.assertEqual(reply["look"]["generation"], self.access.look_generation)
            self.assertEqual(["act", "plain"], [mark["id"] for mark in reply["marks"]])
            self.assertEqual([200, 200, 300, 300], reply["marks"][0]["box"])
            self.assertEqual("tree1", reply["look"]["snapshot_id"])
            image = Image.open(BytesIO(await self.socket.binaries.get()))
            self.assertEqual((800, 600), image.size)
            self.assertNotEqual((30, 90, 200), image.getpixel((200, 200)))
            record = self.entry["snapshots"][reply["snapshot_id"]]
            self.assertEqual([800, 600], record["geometry"]["size"])
            self.assertEqual(reply["look"]["generation"], record["look_generation"])
            self.assertEqual(self.raw, reply["look"]["elements"])
            if source == "cdp":
                self.assertEqual(3, reply["timing"]["ax_tree_ms"])
                self.assertEqual(5, reply["timing"]["cdp_commands"])
                self.assertNotEqual(100, reply["timing"]["total_ms"])
                self.assertNotIn("ax_nodes", reply["timing"])
                self.assertNotIn("mapped_nodes", reply["timing"])

    async def test_thumb_budget_and_mapping_cdp_viewport_bounds(self):
        self.prepare(size=(4000, 3000))
        self.raw[1].pop("bounds")
        self.raw[1]["viewport_bounds"] = [200, 200, 300, 300]
        with patch.object(self.shares.snapshots, "page", AsyncMock(return_value=(100, 100, 2))):
            reply = await self.ask()
        self.assertTrue(reply["ok"], reply)
        width, height = reply["width"], reply["height"]
        self.assertLessEqual(max(width, height), 1000)
        self.assertLessEqual(width * height, 700_000)
        self.assertEqual([round(500 * width / 4000), round(500 * height / 3000),
                          round(700 * width / 4000), round(700 * height / 3000)], reply["marks"][0]["box"])

    async def test_marks_never_reused_truncation_and_query(self):
        self.prepare()
        self.part["elements"] = [{"id": str(i), "name": str(i), "bounds": [20, 20, 60, 60]}
                                 for i in range(100)]
        first = await self.ask()
        self.assertTrue(first["look"]["truncated"])
        self.assertEqual(80, len(first["marks"]))
        second = await self.ask(query="=99")
        self.assertEqual(["99"], [mark["id"] for mark in second["marks"]])
        self.assertGreater(second["marks"][0]["n"], first["marks"][-1]["n"])
        with self.assertRaisesRegex(ValueError, "take a fresh screen_window_look"):
            check(self.access, {"look_generation": first["look"]["generation"]})

    async def test_a_hidden_picked_tab_cannot_pair_its_tree_with_another_tabs_image(self):
        self.prepare("cdp")
        self.access.grant["target_id"] = "tab"
        page = SimpleNamespace(visible=AsyncMock(return_value=False))
        with patch.object(self.shares.chrome, "page", AsyncMock(return_value=page)):
            reply = await self.ask()
        self.assertFalse(reply["ok"])
        self.assertIn("take a fresh screen_window_look", reply["error"])
        self.assertEqual(["read"], self.events)
        self.assertTrue(self.socket.binaries.empty())

    async def test_off_image_candidates_do_not_consume_visible_box_budget(self):
        self.prepare()
        self.part["elements"] = [{"id": str(i), "bounds": [2000, 2000, 2010, 2010]} for i in range(90)]
        self.part["elements"] += self.raw
        reply = await self.ask()
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(["act", "plain"], [mark["id"] for mark in reply["marks"]])
        self.assertEqual([1, 2], [mark["n"] for mark in reply["marks"]])
        self.assertFalse(reply["look"]["truncated"])
        self.assertEqual(self.raw, reply["look"]["elements"])

    async def test_event_during_capture_delivers_image_with_changing_note(self):
        self.prepare()
        grab = self.backend.grab
        def changed(hwnd):
            image = grab(hwnd)
            self.access.event_status = lambda: {"event_counter": 5}
            return image
        self.backend.grab = changed
        reply = await self.ask()
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["look"]["changing"])
        self.assertFalse(self.socket.binaries.empty())
        self.assertEqual(reply["look"]["generation"], self.access.look_generation)
        self.assertEqual(["act", "plain"], [mark["id"] for mark in reply["marks"]])

    async def test_events_during_read_and_continuation_keep_a_bounded_changing_look(self):
        self.prepare()
        first = {**self.part, "changed": True, "next_cursor": "next", "truncated": True}
        with patch.object(self.worker, "snapshot", AsyncMock(side_effect=[first, {
                "elements_unavailable": "tree inconsistent: CDP continuation changed; refresh"}])):
            reply = await self.ask()
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["look"]["changing"])
        self.assertTrue(reply["look"]["truncated"])
        self.assertEqual(self.raw, reply["look"]["elements"])

    async def test_regular_reads_and_actions_preserve_the_latest_look_generation(self):
        self.prepare()
        reply = await self.ask()
        generation = reply["look"]["generation"]
        async with self.worker.operation_lock:
            await self.worker.snapshot({}, {})
        self.assertEqual(generation, self.access.look_generation)
        self.worker.session.chrome = SimpleNamespace(action=AsyncMock(return_value={"status": "completed"}))
        self.worker.session.send = AsyncMock()
        await self.worker._action({"request_id": "a", "look_generation": generation, "action": "invoke"})
        self.assertEqual("completed", self.worker.session.send.call_args.kwargs["status"])
        self.assertEqual(generation, self.access.look_generation)

    async def test_parts_disagree_read_failure_and_busy_refuse(self):
        self.prepare()
        self.part["elements_unavailable"] = "closed"
        reply = await self.ask()
        self.assertFalse(reply["ok"])
        self.assertNotIn("capture", self.events)
        self.part.pop("elements_unavailable")
        self.part["next_cursor"] = "next"
        with patch.object(self.worker, "snapshot", AsyncMock(side_effect=[self.part, {
                **self.part, "snapshot_id": "new"}])):
            reply = await self.ask()
        self.assertFalse(reply["ok"])
        self.worker.task = asyncio.create_task(asyncio.Event().wait())
        reply = await self.ask()
        self.assertFalse(reply["ok"])
        self.worker.task.cancel()
        await asyncio.gather(self.worker.task, return_exceptions=True)

    async def test_queued_look_holds_lock_until_capture_and_action_cannot_interleave(self):
        self.prepare()
        entered, release = asyncio.Event(), asyncio.Event()
        read = self.access.snapshot
        async def paused(*args):
            entered.set()
            await release.wait()
            return await read(*args)
        self.access.snapshot = paused
        look = asyncio.create_task(self.ask())
        await entered.wait()
        async def action():
            async with self.worker.operation_lock:
                self.events.append("action")
        action_task = asyncio.create_task(action())
        release.set()
        reply = await look
        await action_task
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(["read", "capture", "action"], self.events)

    async def test_stale_named_action_and_point_mark_are_refused_on_helper(self):
        self.prepare()
        self.access.elements = {}
        self.access.look_generation = "latest"
        self.worker.session.send = AsyncMock()
        await self.worker._action({"request_id": "a", "look_generation": "old", "action": "invoke"})
        named = self.worker.session.send.call_args.kwargs
        self.assertEqual("failed", named["status"])
        self.assertIn("take a fresh screen_window_look", named["error"])
        await self.shares.clicks.handle(self.entry, {"request_id": "b", "grant_id": "g1",
                                                    "look_generation": "old"})
        reply = await self.socket.next("window_element_result")
        self.assertEqual("failed", reply["status"])
        self.assertIn("take a fresh screen_window_look", reply["error"])


from tests import test_helper_window_click as point_cases


class MarkPointGuardTests(point_cases.ClickFixture):
    async def click(self, x=100, y=100, **extra):
        self.access.look_generation = "look"
        return await point_cases.ClickFixture.click(self, x, y, look_generation="look", **extra)

    async def test_point_action_preserves_the_latest_look_generation(self):
        reply = await self.click()
        self.assertEqual("completed", reply["status"], reply)
        self.assertEqual("look", self.access.look_generation)

    test_hard_floor = point_cases.CursorRouteTests.test_a_hard_floor_grant_is_refused_before_anything_else
    test_consent = point_cases.CursorRouteTests.test_a_deny_refuses_and_is_not_asked_again_until_the_cooldown
    test_cover = point_cases.CursorRouteTests.test_what_is_under_the_point_must_be_the_window_or_its_dialogs
    test_deadline = (point_cases.DeadlineTests.
                     test_a_consent_that_arrives_after_the_deadline_is_discarded_and_nothing_is_sent)
    refused = point_cases.RefusalTests.refused
    test_stale = point_cases.RefusalTests.test_a_moved_resized_or_regranted_window_makes_the_snapshot_stale
    test_geometry = point_cases.RefusalTests.test_points_outside_the_client_area_or_the_image_are_refused


class MarkCdpGuardTests(point_cases.ClickFixture):
    click = MarkPointGuardTests.click
    def setUp(self):
        super().setUp()
        self.access.grant["process"] = "chrome.exe"
        self.shares.chrome.page = AsyncMock(return_value=self.page)
        self.shares.clicks.pointer = Mock(return_value=self.pointer)  # landing evidence reads, never input
        self.snapshot = self.take()

    async def test_cdp(self):
        await (point_cases.CdpRouteTests.
               test_a_chrome_page_is_clicked_through_cdp_at_page_pixels_and_never_the_cursor)(self)
        reads = {"foreground", "window_at"}  # the only pointer calls the landing evidence may make
        self.assertEqual([], [call for call in self.pointer.calls
                              if (call if isinstance(call, str) else call[0]) not in reads])
