"""Screen request cleanup and stop races, synchronized without timers."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.screen_frames import BufferedFrame, ShareBuffer
from partyline.screen_protocol import HelperFrame
from partyline.screen_routes import register_screen_routes


class Socket:
    def __init__(self, *, block=False, fail=None):
        self.messages = asyncio.Queue()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block, self.fail = block, fail

    async def send_json(self, message):
        self.messages.put_nowait(message)
        self.entered.set()
        if self.block:
            await self.release.wait()
        if self.fail:
            raise self.fail


class ScreenRequestTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.tmp.name}/test.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        store = MediaStore(self.db, Path(self.tmp.name) / "media")
        self.hub = register_screen_routes(app, self.runtime, store)
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("password1"))
        token = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), user["id"])
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver",
                                  headers={"Authorization": f"Bearer {token}"})
        self.share = ShareBuffer("share", "line", "device", user["id"], "person",
                                 {"x": 0, "y": 0, "width": 10, "height": 10}, status="active")
        self.share.add(BufferedFrame(b"frame", 1, self.share.region, 10, 10, None, "image/png"))
        self.hub.shares["line"] = self.share

    async def asyncTearDown(self):
        await self.client.aclose()
        self.db.close()
        self.tmp.cleanup()

    def device(self, socket):
        self.hub.devices["device"] = {"id": "device", "owner_id": self.share.owner_id,
                                      "socket": socket, "monitors": [{"id": 1}]}

    async def test_screen_elements_route(self):
        with patch.object(self.hub.elements, "read",
                          return_value={"elements_unavailable": "not consented"}) as read:
            response = await self.client.post("/api/conversations/line/screen-elements?device=PC")
        self.assertEqual(response.json(), {"elements_unavailable": "not consented"})
        read.assert_awaited_once()
        principal, device, window = read.await_args.args
        self.assertEqual(("user", "person", "PC", None), (principal.kind, principal.name, device, window))

    async def test_failed_sends_clean_both_waiter_maps(self):
        from fastapi import WebSocketDisconnect

        for failure in (OSError("disconnected"), WebSocketDisconnect(code=1006)):
            self.device(Socket(fail=failure))
            for _ in range(3):
                _, frame = await self.hub.capture("line")
                self.assertEqual(frame.data, b"frame")
                with self.assertRaisesRegex(ValueError, "disconnected"):
                    await self.hub.preview("device", self.share.owner_id, "1")
                self.assertEqual(self.hub.snap_waiters, {})
                self.assertEqual(self.hub.preview_waiters, {})

    async def test_cancellation_during_send_cleans_both_waiter_maps(self):
        for operation in ("snap", "preview"):
            socket = Socket(block=True)
            self.device(socket)
            action = (self.hub.capture("line") if operation == "snap" else
                      self.hub.preview("device", self.share.owner_id, "1"))
            task = asyncio.create_task(action)
            await socket.entered.wait()
            self.assertTrue(self.hub.snap_waiters if operation == "snap" else self.hub.preview_waiters)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(self.hub.snap_waiters, {})
            self.assertEqual(self.hub.preview_waiters, {})

    async def test_send_deadlines_are_bounded(self):
        self.device(Socket(block=True))
        with patch("partyline.screen_requests.SNAP_TIMEOUT_SECONDS", 0):
            _, frame = await self.hub.capture("line")
        self.assertEqual(frame.data, b"frame")
        with patch("partyline.screen_requests.PREVIEW_TIMEOUT_SECONDS", 0):
            with self.assertRaises(TimeoutError):
                await self.hub.preview("device", self.share.owner_id, "1")
        self.assertEqual(self.hub.snap_waiters, {})
        self.assertEqual(self.hub.preview_waiters, {})

    async def test_stop_cancels_pending_capture_and_clears_buffer(self):
        socket = Socket()
        self.device(socket)
        task = asyncio.create_task(self.hub.capture("line"))
        self.assertEqual((await socket.messages.get())["type"], "snap")
        await self.hub.stop_share("share")
        with self.assertRaisesRegex(ValueError, "stopped"):
            await task
        self.assertEqual(self.share.frames, [])
        self.assertEqual(self.hub.snap_waiters, {})

    async def test_stop_cancels_only_waiters_for_that_share(self):
        first_socket, second_socket = Socket(), Socket()
        self.device(first_socket)
        other = ShareBuffer("other", "other-line", "other-device", self.share.owner_id,
                            "person", self.share.region, status="active")
        other.add(BufferedFrame(b"other", 1, other.region, 10, 10, None, "image/png"))
        self.hub.shares["other-line"] = other
        self.hub.devices["other-device"] = {"id": "other-device", "owner_id": other.owner_id,
                                            "socket": second_socket, "monitors": [{"id": 1}]}
        tasks = [asyncio.create_task(self.hub.capture("line")) for _ in range(2)]
        await first_socket.messages.get()
        await first_socket.messages.get()
        remaining = asyncio.create_task(self.hub.capture("other-line"))
        await second_socket.messages.get()
        await self.hub.stop_share("share")
        for task in tasks:
            with self.assertRaisesRegex(ValueError, "stopped"):
                await task
        self.assertEqual(len(self.hub.snap_waiters), 1)
        _, future = next(iter(self.hub.snap_waiters.values()))
        self.assertFalse(future.cancelled())
        future.set_result(other.frames[-1])
        share, frame = await remaining
        self.assertIs(share, other)
        self.assertEqual(frame.data, b"other")
        self.assertEqual(self.hub.snap_waiters, {})

    async def test_resolved_frame_is_not_persisted_after_stop(self):
        socket = Socket()
        self.device(socket)
        received, resume = asyncio.Event(), asyncio.Event()
        async def hold_after_result(future):
            frame = await future
            received.set()
            await resume.wait()
            return frame
        with patch("partyline.screen_requests._await_frame", side_effect=hold_after_result):
            request = asyncio.create_task(self.client.post("/api/conversations/line/screen-frame"))
            command = await socket.messages.get()
            frame = HelperFrame(type="frame", share_id="share", request_id=command["request_id"],
                                ts_ms=2, region=self.share.region, out_width=10, out_height=10,
                                pointer=None, mime="image/png")
            self.hub._frame({"id": "device"}, frame, b"not persisted")
            await received.wait()
            await self.hub.stop_share("share")
            self.hub.shares["line"] = ShareBuffer("new", "line", "device", self.share.owner_id,
                                                  "person", self.share.region, status="active")
            resume.set()
            response = await request
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.db._exec("SELECT COUNT(*) FROM images").fetchone()[0], 0)
        self.assertEqual(self.share.frames, [])
        self.assertEqual(self.hub.snap_waiters, {})
