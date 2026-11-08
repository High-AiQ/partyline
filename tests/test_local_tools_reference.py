"""Overlay references are line-scoped, bounded and passed through the helper to the add-on."""
import asyncio
import base64
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from partyline import local_tools_reference as reference
from partyline.mcp import tools_blender
from partyline.screen_frame_store import store_frame
from partyline_helper.bounds import MAX_MESSAGE_BYTES
from tests.test_local_tools_media import RenderHelpers, png
from tests.test_local_tools_server import CALL, FlowCase


class ReferenceSchema(unittest.TestCase):
    def test_schema_validates_and_passes_overlay_arguments(self):
        calls = []
        state = {"actions": ["write"]}
        client = SimpleNamespace(home="line", request=lambda *a, **k: calls.append((a, k)))
        args = {"reference": "media-id", "overlay_opacity": 0.4, "camera": "Hero", "timeout_s": 90}
        tools_blender.call(client, "blender_render", args, state)
        self.assertEqual(calls[0], (("POST", CALL, {"op": "render", "timeout_s": 90,
            "args": {"reference": "media-id", "overlay_opacity": 0.4, "camera": "Hero"}}), {"timeout": 105}))
        for args in ({"reference": ""}, {"reference": {}}, {"reference": "x" * 81},
                     {"overlay_opacity": -0.1}, {"overlay_opacity": 1.1}, {"overlay_opacity": True}):
            with self.assertRaises(ValueError):
                tools_blender.call(client, "blender_render", args, state)

    def test_worst_case_reference_envelope_fits_installed_helper_and_addon(self):
        encoded = base64.b64encode(b"x" * reference.MAX_REFERENCE_BYTES).decode("ascii")
        args = {"reference": {"id": "\U0001f600" * 80, "png_base64": encoded},
                "camera": "\U0001f600" * 200, "overlay_opacity": 0.1234567890123456,
                "width": 100000, "height": 100000, "samples": 100000,
                "engine": "workbench", "frame": -1000000}
        message = {"type": "tool_call", "session_id": "s" * 128, "call_id": "c" * 128,
                   "op": "render", "args": args, "timeout": 180.0}
        self.assertEqual(reference.MAX_HELPER_MESSAGE_BYTES, MAX_MESSAGE_BYTES)
        reference.validate_message(message)
        self.assertLessEqual(len(json.dumps(message).encode()), MAX_MESSAGE_BYTES)
        addon_body = {"session": message["session_id"], "call_id": message["call_id"],
                      "op": "render", "args": args, "timeout": 180.0}
        # Add-on HTTP contract; its own tests check this against server.MAX_BODY.
        self.assertLessEqual(len(json.dumps(addon_body).encode()), 3 * 1024 * 1024)



class ReferenceFlow(RenderHelpers, FlowCase):
    async def upload_reference(self, data=None, conv_id="line"):
        return await store_frame(self.store, conv_id, data if data is not None else png(), "image/png")

    async def test_reference_is_resolved_to_png_and_forwarded_with_opacity_and_deadline(self):
        await self.connect()
        await self.grant()
        ref = await self.upload_reference()
        answer = await self.render(args={"reference": ref.id, "overlay_opacity": 0.4}, timeout_s=7)
        self.assertEqual(answer.status_code, 200, answer.text)
        session_id, call_id, op, args, timeout = self.addon.calls[-1]
        self.assertEqual((session_id, op, timeout), (self.item().session_id, "render", 7))
        self.assertEqual(args["overlay_opacity"], 0.4)
        self.assertEqual(args["reference"]["id"], ref.id)
        data = base64.b64decode(args["reference"]["png_base64"], validate=True)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual((image.format, image.size, image.mode), ("PNG", (64, 48), "RGB"))
        self.assertNotEqual(answer.json()["file"]["id"], ref.id)
        self.assertEqual(self.session.tools.calls, {})

    async def test_reference_alpha_is_retained_when_present(self):
        await self.connect()
        await self.grant()
        output = io.BytesIO()
        Image.new("RGBA", (64, 48), (50, 100, 150, 70)).save(output, "PNG")
        ref = await self.upload_reference(output.getvalue())
        answer = await self.render(args={"reference": ref.id})
        self.assertEqual(answer.status_code, 200, answer.text)
        payload = self.addon.calls[-1][3]["reference"]["png_base64"]
        with Image.open(io.BytesIO(base64.b64decode(payload))) as image:
            self.assertEqual((image.mode, image.getpixel((0, 0))), ("RGBA", (50, 100, 150, 70)))

    async def test_oversized_envelope_is_refused_without_dropping_helper(self):
        await self.connect()
        await self.grant()
        ref = await self.upload_reference()
        answer = await self.render(args={"reference": ref.id, "extra": "\U0001f600" * 100000})
        self.assertEqual(answer.status_code, 409, answer.text)
        self.assertIn("1 MB message limit", answer.json()["detail"])
        self.assertEqual(self.addon.calls, [])
        self.assertEqual(self.item().status, "active")
        self.assertEqual((await self.render(args={"reference": ref.id})).status_code, 200)

    async def test_other_lines_missing_images_and_paths_are_refused_without_relay_calls(self):
        await self.connect()
        await self.grant()
        self.db.create_conversation("other", "Other")
        other = await self.upload_reference(conv_id="other")
        for value in (other.id, "missing", "/some/reference.png", {"png_base64": "anything"}, ""):
            answer = await self.render(args={"reference": value})
            self.assertEqual(answer.status_code, 409, answer.text)
        self.assertEqual(self.addon.calls, [])
        ref = await self.upload_reference()
        found = self.store.file_for(ref.id, "original")[0]
        found.write_bytes(b"not an image")
        answer = await self.render(args={"reference": ref.id})
        self.assertIn("not a readable image", answer.json()["detail"])
        found.unlink()
        answer = await self.render(args={"reference": ref.id})
        self.assertIn("can no longer be read", answer.json()["detail"])

    async def test_size_caps_and_opacity_are_checked_before_sending(self):
        await self.connect()
        await self.grant()
        ref = await self.upload_reference()
        for limit, value, text in (("MAX_SOURCE_BYTES", 8, "source exceeds"),
                                   ("MAX_REFERENCE_BYTES", 8, "PNG exceeds"),
                                   ("MAX_SIDE", 32, "dimensions must")):
            with patch.object(reference, limit, value):
                answer = await self.render(args={"reference": ref.id})
            self.assertEqual(answer.status_code, 409, answer.text)
            self.assertIn(text, answer.json()["detail"])
        for opacity in (-1, 2, True, "0.5"):
            answer = await self.render(args={"reference": ref.id, "overlay_opacity": opacity})
            self.assertEqual(answer.status_code, 409, answer.text)
        self.assertEqual(self.addon.calls, [])

    async def test_revoke_while_preparing_reference_prevents_sending(self):
        await self.connect()
        await self.grant()
        ref = await self.upload_reference()
        original = asyncio.to_thread
        async def prepare(function, *args, **kwargs):
            result = await original(function, *args, **kwargs)
            if function is reference.prepare:
                await self.hub.tools.revoke(self.item(), "withdrawn while loading")
            return result
        with patch("partyline.local_tools.asyncio.to_thread", side_effect=prepare):
            answer = await self.render(args={"reference": ref.id})
        self.assertEqual(answer.status_code, 409, answer.text)
        self.assertIn("revoked before the call", answer.json()["detail"])
        self.assertEqual(self.addon.calls, [])
