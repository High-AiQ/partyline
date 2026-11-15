"""The helper's window screenshots: a fake capture backend, a fake clock, and the request/answer protocol."""
import asyncio
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from partyline_helper import __version__
from partyline_helper.client import Session
from partyline_helper.window_grab import GrabError, WindowGrab
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.window_shares import WINDOWS_VERSION, WindowShares
from partyline_helper import window_snapshot
from partyline_helper.window_snapshot import MINIMIZED, SNAPSHOT_VERSION, prepare
from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal

GRANT = {"hwnd": 10, "pid": 42, "title": "Editor", "process": "editor.exe"}


class FakeBackend:
    def __init__(self, image=None, minimized=False, error=None):
        self.image = image or Image.new("RGB", (800, 600), (30, 90, 200))
        self.is_minimized, self.error, self.calls = minimized, error, []

    def minimized(self, hwnd):
        self.calls.append(("minimized", hwnd))
        return self.is_minimized

    def grab(self, hwnd):
        self.calls.append(("grab", hwnd))
        if self.error:
            raise self.error
        return self.image


class HelperSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.socket = FakeSocket()
        self.session = Session(self.socket, FakeDesktop(), FakeTerminal(), "Desktop")
        self.session.tools.audit = SimpleNamespace(append=Mock(), ensure_writable=Mock())
        self.shares = WindowShares(self.session)
        self.session.windows = self.shares
        self.shares.chrome.revoke = Mock()  # snapshot fixture has no CDP sessions
        self.backend = FakeBackend()
        self.shares.snapshots.backend = self.backend
        self.shares.snapshots.clock = lambda: 1_700_000_000.0
        self.access = SimpleNamespace(grant=dict(GRANT), generation=3, check=AsyncMock(return_value=None),
                                      revoke=Mock(), gate=DispatchGate())
        self.access.gate.grant()
        self.entry = {"access": self.access, "target": {"line_name": "Alpha"}, "title": "Editor",
                      "worker": SimpleNamespace(cancel=Mock(), close=AsyncMock())}
        self.shares.grants["g1"] = self.entry

    async def asyncTearDown(self):
        await self.shares.close()

    async def ask(self, **extra):
        message = {"type": "snapshot_window", "request_id": "r1", "grant_id": "g1", "agent": "alice", **extra}
        await self.shares.dispatch(message)
        await asyncio.gather(*self.shares.tasks)
        replies = [item for item in self.socket.sent if isinstance(item, dict)
                   and item["type"] == "window_snapshot"]
        return replies[-1], self.socket.binaries

    async def test_the_window_is_captured_and_answered_with_its_request_id_and_bytes(self):
        reply, binaries = await self.ask()
        self.assertEqual(("r1", True, True, "image/png", 800, 600),
                         (reply["request_id"], reply["ok"], reply["media"], reply["mime"],
                          reply["width"], reply["height"]))
        self.assertNotIn("blank", reply)
        self.assertEqual([("minimized", 10), ("grab", 10)], self.backend.calls)
        self.assertEqual(b"\x89PNG", (await binaries.get())[:4])
        self.session.tools.audit.append.assert_called_once()
        self.assertEqual(("event", "window", "alice", "window_snapshot"),
                         self.session.tools.audit.append.call_args.args[:4])

    async def test_the_tray_label_shows_the_last_screenshot_and_who_took_it(self):
        await self.ask()
        self.assertEqual("alice", self.entry["last_screenshot"]["by"])
        label = self.session.status.window_grants["g1"]
        self.assertRegex(label, r"Editor → «Alpha» \(and its sublines\) "
                                r"\(last screenshot \d\d:\d\d by @alice\)$")

    async def test_a_minimised_window_is_refused_and_never_captured(self):
        self.backend.is_minimized = True
        reply, _ = await self.ask()
        self.assertEqual((False, MINIMIZED, "r1"), (reply["ok"], reply["error"], reply["request_id"]))
        self.assertEqual([("minimized", 10)], self.backend.calls)
        self.assertNotIn("last_screenshot", self.entry)

    async def test_the_window_is_sent_at_its_own_size_losslessly(self):
        self.backend.image = Image.new("RGB", (4000, 2500), (1, 2, 3))
        reply, binaries = await self.ask()
        self.assertEqual((4000, 2500, "image/png"), (reply["width"], reply["height"], reply["mime"]))
        sent = Image.open(BytesIO(await binaries.get()))
        self.assertEqual((4000, 2500), sent.size)

    async def test_a_window_too_detailed_for_one_message_loses_quality_never_pixels(self):
        image = Image.effect_noise((600, 400), 80).convert("RGB")
        with patch.object(window_snapshot, "MAX_BYTES", 400_000):
            data, mime, _ = prepare(image)
        self.assertEqual("image/webp", mime)
        self.assertEqual((600, 400), Image.open(BytesIO(data)).size)
        with patch.object(window_snapshot, "MAX_BYTES", 100):
            with self.assertRaisesRegex(GrabError, "too detailed"):
                prepare(image)

    async def test_a_revoke_while_the_image_is_encoded_sends_no_bytes(self):
        def revoking(image):
            self.access.generation += 1
            return b"image", "image/png", False
        with patch.object(window_snapshot, "prepare", revoking):
            reply, binaries = await self.ask()
        self.assertEqual((False, "consent revoked", "r1"), (reply["ok"], reply["error"], reply["request_id"]))
        self.assertTrue(binaries.empty())
        self.assertNotIn("last_screenshot", self.entry)
        self.session.tools.audit.append.assert_not_called()

    async def test_a_revoke_while_the_reply_waits_for_the_writer_lock_sends_no_bytes(self):
        await self.session.lock.acquire()  # another message holds the socket's writer
        await self.shares.dispatch({"type": "snapshot_window", "request_id": "r1", "grant_id": "g1",
                                    "agent": "alice"})
        for _ in range(60):
            await asyncio.sleep(0)  # the capture finishes and the reply queues behind the lock
        self.assertEqual(1, self.backend.calls.count(("grab", 10)))
        self.access.generation += 1  # consent ends while the pixels wait
        self.session.lock.release()
        await asyncio.gather(*self.shares.tasks)
        replies = [item for item in self.socket.sent if isinstance(item, dict)
                   and item["type"] == "window_snapshot"]
        self.assertEqual([(False, "consent revoked", "r1")],
                         [(item["ok"], item["error"], item["request_id"]) for item in replies])
        self.assertTrue(self.socket.binaries.empty())
        self.assertNotIn("last_screenshot", self.entry)
        self.session.tools.audit.append.assert_not_called()

    async def test_an_image_larger_than_one_message_travels_as_chunks_that_rejoin_exactly(self):
        self.backend.image = Image.effect_noise((300, 200), 90).convert("RGB")
        with patch.object(window_snapshot, "CHUNK", 20_000):
            reply, binaries = await self.ask()
        self.assertGreater(reply["chunks"], 2)
        data = b"".join([binaries.get_nowait() for _ in range(reply["chunks"])])
        self.assertTrue(binaries.empty())
        self.assertEqual((300, 200), Image.open(BytesIO(data)).size)
        self.assertEqual((reply["mime"], reply["ok"]), ("image/png", True))

    async def test_a_window_that_closes_while_the_image_is_encoded_sends_no_bytes(self):
        results = iter([None, "window closed"])
        self.access.check.side_effect = lambda grant: next(results)
        reply, binaries = await self.ask()
        self.assertEqual((False, "window closed"), (reply["ok"], reply["error"]))
        self.assertTrue(binaries.empty())

    async def test_an_all_black_window_says_so(self):
        self.backend.image = Image.new("RGB", (100, 80), (0, 0, 0))
        reply, _ = await self.ask()
        self.assertTrue(reply["blank"])

    async def test_a_revoked_or_unknown_grant_is_answered_not_dropped(self):
        del self.shares.grants["g1"]
        reply, _ = await self.ask()
        self.assertEqual((False, "consent revoked"), (reply["ok"], reply["error"]))

    async def test_a_window_that_closed_revokes_its_grant_and_is_reported(self):
        self.access.check.return_value = "window closed"
        reply, _ = await self.ask()
        self.assertEqual((False, "window closed"), (reply["ok"], reply["error"]))
        self.access.revoke.assert_called_once_with("window closed")
        self.assertEqual([], self.backend.calls)

    async def test_a_secure_desktop_is_reported_without_revoking(self):
        self.access.check.return_value = "secure desktop active"
        reply, _ = await self.ask()
        self.assertEqual("secure desktop active", reply["error"])
        self.access.revoke.assert_not_called()

    async def test_a_revoke_during_the_capture_sends_no_image(self):
        def grab(hwnd):
            self.access.generation += 1
            return self.backend.image
        self.backend.grab = grab
        reply, binaries = await self.ask()
        self.assertEqual((False, "consent revoked"), (reply["ok"], reply["error"]))
        self.assertTrue(binaries.empty())

    async def test_capture_failures_become_answers_with_the_request_id(self):
        self.backend.error = GrabError("Graphics Capture produced no frame")
        reply, _ = await self.ask()
        self.assertEqual("Graphics Capture produced no frame", reply["error"])
        self.backend.error = RuntimeError("boom")
        with patch("builtins.print"):
            reply, _ = await self.ask()
        self.assertEqual(("r1", False), (reply["request_id"], reply["ok"]))
        self.assertNotIn("boom", reply["error"])

    async def test_an_unwritable_audit_sends_no_image(self):
        self.session.tools.audit.append.side_effect = OSError("disk")
        with patch("builtins.print"):
            reply, binaries = await self.ask()
        self.assertFalse(reply["ok"])
        self.assertTrue(binaries.empty())

    async def test_a_closed_socket_ends_the_answer_quietly(self):
        from websockets.exceptions import ConnectionClosed

        self.socket.send = AsyncMock(side_effect=ConnectionClosed(None, None))
        await self.ask_without_replies()

    async def ask_without_replies(self):
        await self.shares.dispatch({"type": "snapshot_window", "request_id": "r2", "grant_id": "g1"})
        await asyncio.gather(*self.shares.tasks)

    async def test_the_session_routes_the_request_and_answers_one_without_a_grant_as_unsupported(self):
        await self.session.dispatch({"type": "snapshot_window", "request_id": "r9", "grant_id": "g1"})
        await asyncio.gather(*self.shares.tasks)
        self.assertTrue((await self.socket.next("window_snapshot"))["ok"])
        await self.session.dispatch({"type": "snapshot_window", "request_id": "r10"})
        error = await self.socket.next("error")
        self.assertEqual(("r10", "unsupported: snapshot_window"), (error["request_id"], error["message"]))

    async def test_the_hello_announces_screenshots_and_the_minor_version_moved(self):
        self.assertEqual(3, WINDOWS_VERSION)
        self.assertEqual(2, SNAPSHOT_VERSION)
        self.assertEqual("1.4.0", __version__)


class WindowGrabTests(unittest.TestCase):
    def test_other_platforms_refuse_plainly(self):
        with patch("partyline_helper.window_grab.sys.platform", "linux"):
            for call in (WindowGrab().minimized, WindowGrab().grab):
                with self.assertRaisesRegex(GrabError, "need Windows"):
                    call(10)

    def test_graphics_capture_is_used_and_print_window_is_the_fallback(self):
        grab = WindowGrab()
        image = Image.new("RGB", (5, 5))
        grab.wgc = Mock(return_value=image)
        grab.print_window = Mock(return_value="printed")
        grab.iconic = Mock(return_value=True)
        passthrough = lambda hwnd, capture: capture(hwnd)  # noqa: E731
        with (patch("partyline_helper.window_grab.sys.platform", "win32"),
              patch("partyline_helper.window_grab_owned.grab_owned", side_effect=passthrough)):
            self.assertIs(image, grab.grab(10))
            self.assertTrue(grab.minimized(10))
            grab.wgc.side_effect = GrabError("no frame")
            self.assertEqual("printed", grab.grab(10))
        grab.print_window.assert_called_once_with(10)
