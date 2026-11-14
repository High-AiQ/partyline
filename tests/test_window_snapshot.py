"""Window screenshots: line access, native size, variants, audit, storage and consent, with a fake capture."""
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from partyline.screen_window_snapshot import OLD_HELPER, image_tokens
from tests.window_grant_fixtures import WindowGrantFixture


def picture(width=400, height=300, color=(200, 30, 30), fmt="WEBP"):
    out = BytesIO()
    Image.new("RGB", (width, height), color).save(out, fmt)
    return out.getvalue()


class SnapshotFixture(WindowGrantFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub.snapshots.wall = lambda: 1_700_000_000.0
        self.answer = {"ok": True, "mime": "image/webp", "media": True}
        self.image = picture()
        self.device["socket"].receive_bytes = self.next_bytes
        self.requests = []

    async def next_bytes(self):
        return self.image

    async def receive(self, message):
        self.sent.append(message)
        if message["type"] == "snapshot_window":
            self.requests.append(message)
            await self.hub.snapshots.from_helper(
                self.device, {"type": "window_snapshot", "request_id": message["request_id"], **self.answer})

    async def shot(self, ident, window=None, headers=None):
        line = self.db.get_attachment(ident)["conv_id"]
        return await self.client.post(f"/api/conversations/{line}/screen-window-snapshot",
                                      params={"window": window} if window else {},
                                      headers=headers or self.machine(ident))


class WindowSnapshotTests(SnapshotFixture, unittest.IsolatedAsyncioTestCase):
    async def test_a_process_on_the_granted_line_gets_one_stored_image(self):
        await self.grant("a")
        response = await self.shot("a")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(("g1", "Editor", 400, 300, False),
                         (body["window"], body["title"], body["width"], body["height"], body["unchanged"]))
        self.assertTrue(body["file"]["id"])
        self.assertNotIn("note", body)
        request = self.requests[0]
        self.assertEqual(("g1", "a"), (request["grant_id"], request["agent"]))
        self.assertTrue(body["file"]["urls"]["slim"].startswith("/api/media/"))  # a path an agent can post

    async def test_a_peer_on_the_same_line_may_use_the_grant_and_another_line_may_not(self):
        await self.grant("a")
        self.assertEqual(200, (await self.shot("peer")).status_code)
        refused = await self.shot("b")
        self.assertEqual(403, refused.status_code)
        self.assertIn("no window is shared with this line", refused.json()["detail"])
        elements = await self.read("b")  # the same refusal elements give
        self.assertEqual(elements.json()["detail"], refused.json()["detail"])
        self.assertEqual(1, len(self.requests))

    async def test_a_machine_credential_needs_line_read_access(self):
        await self.grant("a")
        alpha = self.db.get_attachment("a")["conv_id"]
        response = await self.client.post(f"/api/conversations/{alpha}/screen-window-snapshot",
                                          headers=self.machine("b"))
        self.assertEqual(403, response.status_code)
        self.assertEqual([], self.requests)

    async def test_the_owner_may_take_a_screenshot_of_their_own_window(self):
        await self.grant("a")
        alpha = self.db.get_attachment("a")["conv_id"]
        response = await self.client.post(f"/api/conversations/{alpha}/screen-window-snapshot",
                                          headers=self.human(self.owner))
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("owner", self.requests[0]["agent"])

    async def test_an_ended_grant_is_a_clear_error(self):
        await self.grant("a")
        await self.hub.window_grants.revoke("g1")
        response = await self.shot("a", "g1")
        self.assertEqual(403, response.status_code)
        self.assertIn("ask the person to share one", response.json()["detail"])
        self.assertEqual([], self.requests)

    async def test_a_grant_that_ends_during_the_capture_is_refused(self):
        await self.grant("a")
        original = self.receive

        async def revoking(message):
            if message["type"] == "snapshot_window":
                await self.hub.window_grants.revoke("g1")
            await original(message)
        self.device["socket"].send_json = revoking
        response = await self.shot("a")
        self.assertEqual(403, response.status_code)

    async def test_a_minimised_window_is_reported_by_the_helper_and_stores_nothing(self):
        await self.grant("a")
        self.answer = {"ok": False, "error": "the window is minimised; Partyline never restores it."}
        response = await self.shot("a")
        self.assertEqual(409, response.status_code)
        self.assertIn("minimised", response.json()["detail"])

    async def test_a_helper_without_screenshots_is_refused_without_a_request(self):
        await self.grant("a")
        self.device["windows"] = 1
        response = await self.shot("a")
        self.assertEqual(409, response.status_code)
        self.assertEqual(OLD_HELPER, response.json()["detail"])
        self.assertEqual([], self.requests)

    async def test_the_window_is_stored_at_its_own_size_with_all_three_variants_listed(self):
        await self.grant("a")
        self.image = picture(3200, 1800, fmt="PNG")  # larger than slim, so slim and full differ
        self.answer["mime"] = "image/png"
        body = (await self.shot("a")).json()
        self.assertEqual((3200, 1800), (body["width"], body["height"]))
        self.assertEqual((3200, 1800), (body["file"]["width"], body["file"]["height"]))
        full, slim, thumb = (body["variants"][name] for name in ("full", "slim", "thumb"))
        self.assertEqual((3200, 1800), (full["width"], full["height"]))
        self.assertEqual((1600, 900), (slim["width"], slim["height"]))
        self.assertEqual((512, 288), (thumb["width"], thumb["height"]))
        for name, tier in body["variants"].items():
            self.assertTrue(tier["url"].startswith("/api/media/"), name)
            self.assertEqual(image_tokens(tier["width"], tier["height"]), tier["image_tokens"])
        self.assertTrue(full["url"].endswith("/original"))
        self.assertEqual(full["image_tokens"], slim["image_tokens"])  # a model shrinks both to the same size
        self.assertGreater(slim["image_tokens"], thumb["image_tokens"])
        self.assertIn("slim is the usual choice", body["use"])

    def test_image_tokens_follow_a_models_own_resize(self):
        self.assertEqual(round(512 * 288 / 750), image_tokens(512, 288))
        self.assertEqual(image_tokens(1568, 882), image_tokens(3200, 1800))  # shrunk to its long edge
        self.assertEqual(1533, image_tokens(1600, 900))

    async def test_a_grant_that_ends_after_the_helper_answers_stores_nothing(self):
        await self.grant("a")
        original = self.hub.elements.exchange

        async def exchange(*args, **kwargs):
            answer = await original(*args, **kwargs)
            await self.hub.window_grants.revoke("g1")  # the helper's bytes arrive, then consent ends
            return answer
        self.hub.elements.exchange = exchange
        response = await self.shot("a")
        self.assertEqual(403, response.status_code)
        self.assertEqual([], self.db._exec("SELECT id FROM images").fetchall())
        self.assertEqual([], self.db._exec("SELECT id FROM screen_control_audit").fetchall())

    async def test_a_grant_that_ends_while_the_image_is_stored_leaves_no_media_and_no_answer(self):
        await self.grant("a")
        from partyline import screen_window_snapshot as module
        stored = module.frame_reference

        async def store_then_revoke(*args, **kwargs):
            result = await stored(*args, **kwargs)
            await self.hub.window_grants.revoke("g1")
            return result
        with patch.object(module, "frame_reference", store_then_revoke):
            response = await self.shot("a")
        self.assertEqual(403, response.status_code)
        self.assertNotIn("file", response.json())
        self.assertEqual([], self.db._exec("SELECT id FROM images").fetchall())
        stray = [path for path in Path(self.tmp.name, "media").rglob("*") if path.is_file()]
        self.assertEqual([], stray)
        entries = [row["entry"] for row in self.db._exec("SELECT entry FROM screen_control_audit")]
        self.assertTrue(entries[-1].startswith("window screenshot withheld"), entries)

    async def test_a_grant_that_ends_while_the_line_is_notified_leaves_no_media_and_no_answer(self):
        await self.grant("a")
        broadcast = self.runtime.broadcast

        async def revoking(*args, **kwargs):
            await broadcast(*args, **kwargs)
            await self.hub.window_grants.revoke("g1")  # consent ends during the audit notification
        with patch.object(self.runtime, "broadcast", revoking):
            response = await self.shot("a")
        self.assertEqual(403, response.status_code)
        self.assertNotIn("file", response.json())
        self.assertEqual([], self.db._exec("SELECT id FROM images").fetchall())
        stray = [path for path in Path(self.tmp.name, "media").rglob("*") if path.is_file()]
        self.assertEqual([], stray)
        entries = [row["entry"] for row in self.db._exec("SELECT entry FROM screen_control_audit")]
        self.assertTrue(entries[-1].startswith("window screenshot withheld"), entries)

    async def test_an_image_larger_than_one_binary_message_is_taken_as_chunks(self):
        await self.grant("a")
        self.image = picture(3840, 2160, fmt="PNG")
        size = len(self.image) // 4 + 1
        parts = [self.image[i:i + size] for i in range(0, len(self.image), size)]
        self.assertGreater(len(parts), 2)
        queue = iter(parts)

        async def next_part():
            return next(queue)
        self.device["socket"].receive_bytes = next_part
        self.answer = {"ok": True, "mime": "image/png", "media": True, "chunks": len(parts)}
        response = await self.shot("a")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual((3840, 2160), (body["width"], body["height"]))
        self.answer["chunks"] = 99  # a bad count is read as one message, never an unbounded wait
        queue = iter([b"junk"])
        self.assertEqual(502, (await self.shot("a")).status_code)

    async def test_a_reused_file_survives_a_grant_that_ends_while_it_is_checked(self):
        await self.grant("a")
        first = (await self.shot("a")).json()
        from partyline import screen_window_snapshot as module
        stored = module.frame_reference

        async def reuse_then_revoke(*args, **kwargs):
            result = await stored(*args, **kwargs)
            await self.hub.window_grants.revoke("g1")
            return result
        with patch.object(module, "frame_reference", reuse_then_revoke):
            self.assertEqual(403, (await self.shot("a")).status_code)
        self.assertEqual([first["file"]["id"]], [row["id"] for row in self.db._exec("SELECT id FROM images")])

    async def test_an_unreadable_or_unlisted_image_is_refused(self):
        await self.grant("a")
        for data, mime in ((b"not an image", "image/webp"), (picture(), "image/gif"), (b"", "image/webp")):
            self.image, self.answer["mime"] = data, mime
            with self.subTest(mime=mime, size=len(data)):
                self.assertEqual(502, (await self.shot("a")).status_code)

    async def test_the_same_bytes_again_reuse_the_stored_file_as_unchanged(self):
        await self.grant("a")
        first = (await self.shot("a")).json()
        second = (await self.shot("a")).json()
        self.assertTrue(second["unchanged"])
        self.assertEqual(first["file"]["id"], second["file"]["id"])
        self.image = picture(color=(1, 2, 3))
        third = (await self.shot("a")).json()
        self.assertFalse(third["unchanged"])
        self.assertNotEqual(first["file"]["id"], third["file"]["id"])

    async def test_protected_content_is_reported_as_black(self):
        await self.grant("a")
        self.answer["blank"] = True
        self.assertIn("protected", (await self.shot("a")).json()["note"])

    async def test_every_capture_is_audited_with_who_and_which_grant(self):
        await self.grant("a")
        await self.shot("a")
        await self.shot("peer")
        rows = self.db._exec("SELECT share_id,conv_id,agent,entry FROM screen_control_audit "
                             "ORDER BY id").fetchall()
        self.assertEqual(["a", "peer"], [row["agent"] for row in rows])
        self.assertEqual({"g1"}, {row["share_id"] for row in rows})
        self.assertIn("window screenshot of «Editor» (400x300", rows[0]["entry"])
        notes = [m for m in self.db.list_messages(rows[0]["conv_id"]) if "window screenshot" in m["body"]]
        self.assertEqual(2, len(notes))

    async def test_the_owner_sees_when_and_by_whom_the_last_screenshot_was_taken(self):
        from partyline.screen_snapshot import owner_devices

        await self.grant("a")
        self.assertNotIn("last_screenshot", owner_devices(self.hub, self.owner["id"])[0]["window_grants"][0])
        await self.shot("a")
        grant = owner_devices(self.hub, self.owner["id"])[0]["window_grants"][0]
        self.assertEqual({"at": 1_700_000_000.0, "by": "a"}, grant["last_screenshot"])
        await self.hub.window_grants.revoke("g1")
        self.assertIsNone(self.hub.snapshots.last_screenshot("g1"))

    async def test_a_silent_helper_is_a_gateway_timeout(self):
        await self.grant("a")

        async def silent(message):
            self.sent.append(message)
        self.device["socket"].send_json = silent

        async def timed_out(*_args, **_kwargs):
            raise TimeoutError

        self.hub.elements.exchange = timed_out
        response = await self.shot("a")
        self.assertEqual(504, response.status_code)

    async def test_a_message_without_media_is_answered_without_reading_bytes(self):
        await self.grant("a")
        self.answer = {"ok": False, "error": "consent revoked"}
        self.device["socket"].receive_bytes = None  # would raise if read
        response = await self.shot("a")
        self.assertEqual(409, response.status_code)
        self.assertEqual("consent revoked", response.json()["detail"])


class WindowSnapshotToolTests(unittest.TestCase):
    def test_the_tool_points_agents_at_elements_first_within_the_length_tests(self):
        from partyline.mcp.catalog import EXTRAS_OPS, door, one_line
        from partyline.mcp.tools_screen import WINDOW_SNAPSHOT_NOTE, screen_window_snapshot_tool

        tool = screen_window_snapshot_tool()
        self.assertIn("screen_elements first", tool["description"])
        self.assertIn("layout or visuals", tool["description"])
        self.assertLessEqual(len(one_line(tool["name"], WINDOW_SNAPSHOT_NOTE)), 200)
        self.assertIn("screen_window_snapshot", EXTRAS_OPS)
        self.assertEqual("extras", door("screen_window_snapshot", {"dynamic_screen_tools": True}))

    def test_the_grant_notice_says_to_read_elements_first(self):
        from partyline.screen_window_notices import line_window_text, usage

        text = usage("g1", "Editor", "PC", "me")
        self.assertIn("Read elements first, and the deltas after each action", text)
        self.assertIn('extras(op="screen_window_snapshot", args={"window": "g1"})', text)
        self.assertIn("screen_window_snapshot", line_window_text(
            SimpleNamespace(_exec=lambda *a: SimpleNamespace(fetchall=lambda: [
                {"title": "T", "id": "g1", "device_name": "PC"}])), "c"))


class MonitorRefusalTests(SnapshotFixture, unittest.IsolatedAsyncioTestCase):
    async def test_a_monitor_capture_on_a_line_with_only_a_window_names_the_screenshot_tool(self):
        await self.grant("a")
        alpha = self.db.get_attachment("a")["conv_id"]
        response = await self.client.post(f"/api/conversations/{alpha}/screen-frame",
                                          headers=self.machine("a"))
        self.assertEqual(409, response.status_code)
        detail = response.json()["detail"]
        self.assertIn("no monitor is shared with this line; window «Editor» (g1) is", detail)
        self.assertIn("screen_window_snapshot(window=<id>)", detail)

    async def test_a_line_with_nothing_shared_keeps_the_plain_refusal(self):
        beta = self.db.get_attachment("b")["conv_id"]
        response = await self.client.post(f"/api/conversations/{beta}/screen-frame",
                                          headers=self.machine("b"))
        self.assertEqual("nobody is sharing a screen on this line", response.json()["detail"])

    def test_a_listing_client_without_a_monitor_is_pointed_at_the_window_tool(self):
        from partyline.mcp import catalog
        from partyline.mcp.client import ApiError

        state = {"dynamic_screen_tools": True, "screen_windows": True, "screen_read": False,
                 "actions": ["read"]}
        with self.assertRaisesRegex(ApiError, "a window is: use screen_window_snapshot"):
            catalog.dispatch(None, "screen_frame", {}, state)
        with self.assertRaisesRegex(ApiError, "^no screen shared with you$"):
            catalog.dispatch(None, "screen_frame", {}, {**state, "screen_windows": False})

    async def test_a_helper_that_fails_to_send_is_a_conflict(self):
        await self.grant("a")

        async def broken(*_args, **_kwargs):
            raise OSError("socket closed")
        self.hub.elements.exchange = broken
        response = await self.shot("a")
        self.assertEqual(409, response.status_code)
        self.assertIn("did not take the screenshot", response.json()["detail"])
