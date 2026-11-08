"""Local tool images: stored as line media, the 4 MiB ceiling, refusals, cancel and both audit copies."""
import asyncio
import io
import json
import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from partyline import local_tools_audit, local_tools_media
from partyline.local_tools import ToolSession
from partyline.media import MediaError
from partyline.screen_protocol import MAX_FRAME_BYTES
from partyline_helper import tools_media
from partyline_helper.tools_addon import AddonError
from tests.test_local_tools_server import CALL, FlowCase, until


def png(width=64, height=48, noise=False):
    image = Image.new("RGB", (width, height), (200, 40, 40))
    if noise:
        rng = random.Random(1)
        image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                       for _ in range(width * height)])
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


RESULT = {"ok": True, "artifact": {"id": "a1", "mime": "image/png", "bytes": 1},
          "settings": {"camera": "Camera", "engine": "workbench", "width": 64, "height": 48,
                       "samples": None, "frame": 1}, "adjusted": ["width 5000 -> 2048"], "elapsed": 0.4}


class RenderHelpers:
    """Drive a render or screenshot through the fake add-on (mixed into the flow cases)."""

    async def render(self, op="render", args=None, artifact=None, timeout_s=5):
        self.addon.reply = {"result": dict(RESULT)}
        self.addon.artifacts["a1"] = artifact if artifact is not None else png()
        return await self.client.post(CALL, json={"op": op, "args": args or {}, "timeout_s": timeout_s})

    def helper_rows(self):
        text = (Path(self.tmp.name) / "helper-audit.jsonl").read_text()
        return [json.loads(line) for line in text.splitlines()]


class MediaFlow(RenderHelpers, FlowCase):

    async def test_a_render_is_stored_and_returned_as_a_media_reference(self):
        await self.connect()
        await self.grant()
        answer = await self.render(args={"width": 5000})
        self.assertEqual(answer.status_code, 200, answer.text)
        body = answer.json()
        file = body["file"]  # the screen_frame reference shape: fetch the pixels with get_media
        self.assertEqual((file["kind"], file["mime"], file["width"], file["height"]),
                         ("image", "image/webp", 64, 48))
        self.assertIn("/api/media/", file["urls"]["original"])
        self.assertEqual(body["settings"]["camera"], "Camera")
        self.assertEqual(body["adjusted"], ["width 5000 -> 2048"])           # clamps reach the agent
        self.assertEqual(body["media"]["mime"], "image/webp")
        self.assertNotIn("artifact", body)
        self.assertNotIn("data", body)
        path, mime, _ = self.store.file_for(file["id"], "original")
        with Image.open(path) as stored:
            self.assertEqual((mime, stored.size), ("image/webp", (64, 48)))
        self.assertEqual(self.addon.fetched, [(self.item().session_id, "a1")])
        self.assertEqual(self.item().media_bytes, file["bytes"])
        self.assertEqual(self.bodies().count("Screen frame"), 0)             # no chat post for the image
        self.assertEqual(self.session.tools.calls, {})

    async def test_a_screenshot_takes_the_same_path(self):
        await self.connect()
        await self.grant()
        answer = await self.render("screenshot", {"max_size": 800})
        self.assertEqual(answer.status_code, 200, answer.text)
        file = answer.json()["file"]
        self.assertEqual((file["kind"], file["filename"]), ("image", "local-tool-screenshot"))
        self.assertEqual(self.addon.calls[0][2:4], ("screenshot", {"max_size": 800}))

    async def test_both_audit_copies_record_the_request_and_the_image(self):
        await self.connect()
        await self.grant()
        answer = await self.render(args={"camera": "Side", "width": 640})
        file_id = answer.json()["file"]["id"]
        rows = local_tools_audit.rows(self.db, self.addon.opened[0][0])
        self.assertEqual([r["kind"] for r in rows], ["event", "call", "result"])
        self.assertEqual(rows[1]["entry"], 'render {"camera":"Side","width":640}')
        self.assertIn(f"ok, media {file_id}", rows[2]["entry"])
        helper = self.helper_rows()
        self.assertEqual([(r["kind"], r["op"]) for r in helper], [("event", "session"), ("call", "render"),
                                                                  ("result", "render")])
        self.assertEqual(helper[1]["entry"], 'render {"camera":"Side","width":640}')
        self.assertRegex(helper[2]["entry"], r"^ok \(image/webp, \d+ bytes, 64x48\)$")
        for earlier, later in zip(helper, helper[1:], strict=False):
            self.assertEqual(later["prev"], earlier["hash"])

    async def test_an_image_over_the_ceiling_is_refused_with_a_clear_error(self):
        await self.connect()
        await self.grant()
        with patch.object(tools_media, "MAX_MEDIA", 2000):
            answer = await self.render(artifact=png(120, 90, noise=True))
        self.assertEqual(answer.status_code, 409)
        self.assertIn("over the 4 MiB limit; ask for a smaller size", answer.json()["detail"])
        self.assertIn("120x90", answer.json()["detail"])
        self.assertEqual(self.item().status, "active")                        # the session lives on
        self.assertEqual(self.item().media_bytes, 0)
        self.assertEqual(self.store.list_conversation("line"), [])
        self.assertIn("refused: ", local_tools_audit.rows(self.db, self.item().session_id)[-1]["entry"])
        self.assertTrue(self.helper_rows()[-1]["entry"].startswith("failed: the image is"))
        self.assertEqual((await self.render()).status_code, 200)              # and a smaller one works

    async def test_an_unreadable_or_missing_artifact_is_a_plain_error(self):
        await self.connect()
        await self.grant()
        junk = await self.render(artifact=b"not an image")
        self.assertIn("could not be read", junk.json()["detail"])
        self.addon.reply = {"result": dict(RESULT)}
        missing = await self.client.post(CALL, json={"op": "render", "args": {}, "timeout_s": 5})
        self.assertIn("unknown artifact", missing.json()["detail"])
        self.assertEqual(self.store.list_conversation("line"), [])

    async def test_a_failed_render_is_just_a_script_style_error(self):
        await self.connect()
        await self.grant()
        error = {"type": "NoCamera", "message": "the scene has no active camera", "traceback": ""}
        self.addon.reply = {"result": {"ok": False, "error": error}}
        answer = await self.client.post(CALL, json={"op": "render", "args": {}, "timeout_s": 5})
        self.assertEqual((answer.status_code, answer.json()["error"]["type"]), (200, "NoCamera"))
        self.assertEqual(self.addon.fetched, [])
        self.assertEqual(local_tools_audit.rows(self.db, self.item().session_id)[-1]["entry"],
                         "script error: NoCamera")

    async def test_without_a_grant_render_and_screenshot_are_refused(self):
        await self.connect()
        for op in ("render", "screenshot"):
            answer = await self.render(op)
            self.assertEqual(answer.status_code, 409)
            self.assertIn("not granted", answer.json()["detail"])
        self.assertEqual(self.addon.calls, [])
        await self.grant()
        self.assertEqual((await self.client.post("/api/conversations/line/local-tools/end")).status_code, 200)
        await until(lambda: self.addon.closed)
        for op in ("render", "screenshot"):
            self.assertEqual((await self.render(op)).status_code, 409)
        self.assertEqual(self.addon.calls, [])

    async def test_the_helper_refuses_media_ops_without_its_own_grant(self):
        await self.connect()
        message = dict(type="tool_call", session_id="s", call_id="c1", op="render", args={}, timeout=5)
        await self.session.dispatch(message)
        await until(lambda: self.addon.calls == [] and not self.session.tools.tasks)
        self.assertEqual((self.addon.calls, self.addon.fetched), ([], []))

    async def test_cancel_at_the_deadline_stores_nothing_and_asks_the_add_on_to_stop(self):
        await self.connect()
        await self.grant()
        self.addon.release = asyncio.get_running_loop().create_future()
        waits = []

        def deadline(delay):
            waits.append(asyncio.timeout(None))
            return waits[-1]

        self.hub.tools.deadline = deadline
        call = asyncio.create_task(self.render(timeout_s=60))
        await until(lambda: self.addon.calls)
        waits[0].reschedule(asyncio.get_running_loop().time())  # the deadline passes
        answer = await call
        self.assertEqual(answer.status_code, 409)
        self.assertIn("did not answer in time", answer.json()["detail"])
        await until(lambda: self.addon.cancelled)
        self.assertEqual(self.store.list_conversation("line"), [])
        self.assertEqual(self.addon.fetched, [])

    async def test_the_kill_switch_ends_a_render_in_progress(self):
        await self.connect()
        await self.grant()
        self.addon.release = asyncio.get_running_loop().create_future()
        call = asyncio.create_task(self.render(timeout_s=60))
        await until(lambda: self.addon.calls)
        self.session.status.request_stop_tools()
        answer = await call
        self.assertEqual(answer.status_code, 409)
        self.assertIn("revoked", answer.json()["detail"])
        self.assertEqual(self.item().status, "revoked")
        self.assertIsNone(self.session.tools.grant)
        self.assertEqual(self.store.list_conversation("line"), [])
        self.assertEqual((await self.render()).status_code, 409)

    async def test_a_stale_media_result_does_not_desynchronise_the_stream(self):
        await self.connect()
        await self.grant()
        await self.session.send("tool_result", binary=b"\x00" * 10, call_id="nobody", ok=True, result={},
                                media=True, mime="image/webp")
        answer = await self.run_code()
        self.assertEqual(answer.status_code, 200, answer.text)

    async def test_the_session_stops_taking_images_at_its_media_cap(self):
        await self.connect()
        await self.grant()
        with patch.object(local_tools_media, "SESSION_BYTES", 200):
            first = await self.render(artifact=png(8, 8))
            second = await self.render(artifact=png(64, 48, noise=True))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertIn("session media cap", second.json()["detail"])
        self.assertEqual(len(self.store.list_conversation("line")), 1)


class ServerMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_server_checks_what_the_helper_sent(self):
        item = ToolSession("s", "line", "d", "blender", "agent")
        answer = {"media": True, "mime": "image/webp", "data": b"x"}
        for bad in ({**answer, "data": b""}, {**answer, "data": b"x" * (MAX_FRAME_BYTES + 1)},
                    {**answer, "mime": "text/html"}, {**answer, "data": None},
                    {**answer, "data": b"<html>not an image</html>"}, {**answer, "data": png()[:40]},
                    {**answer, "data": b"\xff\xd8\xff\xe0" + b"junk" * 20}):
            with self.assertRaisesRegex(ValueError, "cannot be used"):
                await local_tools_media.attach(object(), item, "render", {}, bad)
        with self.assertRaisesRegex(ValueError, "cannot be used"):
            await local_tools_media.attach(None, item, "render", {}, answer)
        self.assertEqual(await local_tools_media.attach(None, item, "exec", {"ok": True}, {}), {"ok": True})
        self.assertEqual(local_tools_media.note({"ok": True}), "")

    async def test_the_media_store_refusing_the_image_is_a_plain_error(self):
        item = ToolSession("s", "line", "d", "blender", "agent")
        answer = {"media": True, "mime": "image/webp", "data": png()}
        with patch.object(local_tools_media, "store_frame", side_effect=MediaError(415, "unsupported")), \
                self.assertRaisesRegex(ValueError, "rejected: unsupported"):
            await local_tools_media.attach(object(), item, "render", {}, answer)


class HelperMediaTests(unittest.IsolatedAsyncioTestCase):
    def test_reencode_keeps_the_size_drops_the_format_and_stays_under_the_ceiling(self):
        data, mime, width, height = tools_media.reencode(png(200, 100))
        self.assertEqual((mime, width, height), ("image/webp", 200, 100))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (200, 100))
        self.assertLessEqual(len(data), tools_media.MAX_MEDIA)

    def test_it_falls_back_to_jpeg_without_webp_and_walks_down_the_qualities(self):
        real = Image.Image.save

        def no_webp(image, out, fmt=None, **kw):
            if fmt == "WEBP":
                raise OSError("encoder missing")
            return real(image, out, fmt, **kw)

        with patch.object(Image.Image, "save", no_webp):
            data, mime, *_ = tools_media.reencode(png(50, 50))
        self.assertEqual(mime, "image/jpeg")
        sizes = []
        original = tools_media.encode
        with patch.object(tools_media, "MAX_MEDIA", 1500), \
                patch.object(tools_media, "encode", lambda image, q: sizes.append(q) or original(image, q)):
            with self.assertRaises(tools_media.MediaError):
                tools_media.reencode(png(100, 100, noise=True))
        self.assertEqual(sizes, [85, 70, 50])

    def test_unreadable_oversized_and_decompression_bombs_are_refused(self):
        for data in (b"", b"GIF89a-not-really", png()[:30]):
            with self.assertRaisesRegex(tools_media.MediaError, "could not be read"):
                tools_media.reencode(data)
        with patch.object(tools_media, "MAX_PIXELS", 100), \
                self.assertRaisesRegex(tools_media.MediaError, "larger than expected"):
            tools_media.reencode(png(64, 48))
        with patch.object(Image, "MAX_IMAGE_PIXELS", 10), \
                self.assertRaisesRegex(tools_media.MediaError, "could not be read"):
            tools_media.reencode(png(64, 48))

    def test_only_media_ops_with_an_ok_result_and_an_artifact_count(self):
        has = tools_media.has_image
        self.assertTrue(has("render", RESULT))
        self.assertTrue(has("screenshot", RESULT))
        self.assertFalse(has("exec", RESULT))  # a script cannot ask for a fetch
        self.assertFalse(has("render", {**RESULT, "ok": False}))
        self.assertFalse(has("render", {"ok": True, "artifact": "a1"}))
        self.assertFalse(has("render", None))

    async def test_nothing_is_sent_if_the_session_ended_while_the_image_was_prepared(self):
        sent = []
        addon = SimpleNamespace(artifact=lambda *a: self.async_value(png()))
        grant = {"id": "s", "checker": False, "addon": addon}
        tools = SimpleNamespace(grant=None, log=lambda *a: sent.append(a),
                                send=lambda *a, **k: self.async_value(sent.append(("send", k))))
        await tools_media.deliver(tools, grant, "c", "render", RESULT)
        self.assertEqual(sent, [])
        tools.grant = grant
        await tools_media.deliver(tools, grant, "c", "render", RESULT)
        self.assertEqual([entry[0] for entry in sent], ["result", "send"])
        self.assertTrue(sent[1][1]["media"] and sent[1][1]["ok"])

    async def test_only_a_render_under_a_grant_with_render_checks_is_marked_checkable(self):
        sent = []
        addon = SimpleNamespace(artifact=lambda *a: self.async_value(png()))
        grant = {"id": "s", "checker": False, "addon": addon}
        tools = SimpleNamespace(grant=grant, log=lambda *a: sent.append(a),
                                send=lambda *a, **k: self.async_value(sent.append(("send", k))))
        for op, checker, expected in (("render", True, True), ("render", False, False),
                                      ("screenshot", True, False)):
            sent.clear()
            grant["checker"] = checker
            await tools_media.deliver(tools, grant, "c", op, RESULT)
            self.assertIs(sent[1][1]["checkable"], expected, (op, checker))
            self.assertEqual(", checkable" in sent[0][2], expected)
        grant["checker"] = False  # the scope is read when the image is returned, not when it was asked for
        await tools_media.deliver(tools, grant, "c", "render", RESULT)
        self.assertIs(sent[-1][1]["checkable"], False)

    async def test_an_add_on_error_while_fetching_is_reported_to_the_server(self):
        async def broken(*args):
            raise AddonError("Blender is not reachable (OSError)")

        sent = []
        tools = SimpleNamespace(grant=None, log=lambda *a: None,
                                send=lambda *a, **k: self.async_value(sent.append((a, k))))
        grant = {"id": "s", "checker": False, "addon": SimpleNamespace(artifact=broken)}
        tools.grant = grant
        await tools_media.deliver(tools, grant, "c", "render", RESULT)
        self.assertEqual(sent, [(("tool_result",), {"call_id": "c", "ok": False,
                                                    "error": "Blender is not reachable (OSError)"})])

    @staticmethod
    async def async_value(value):
        return value
