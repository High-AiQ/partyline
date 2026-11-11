"""Regression coverage for native helper review findings; no real desktop access."""
import asyncio
import contextlib
import ctypes
import io
import json
import os
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import URLError

from PIL import Image

from partyline_helper import cli, config, desktop, terminal
from partyline_helper.client import Session
from partyline_helper.transport import CertificateError, certificate_failure
from tests.screen_helper_fakes import (
    FakeDesktop, FakeSocket, FakeTerminal, ManualTime, REGION, checkpoint, request, serve,
)


def bad_certificate():
    error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    error.verify_message = "certificate has expired"
    return error


class CertificateReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_certificate_failure_never_retries(self):
        for error in (bad_certificate(), URLError(bad_certificate())):
            sleep = AsyncMock(side_effect=AssertionError("Certificate failures must not retry"))
            with patch("partyline_helper.client.connect", side_effect=error) as connecting:
                with self.assertRaisesRegex(CertificateError, "screen.example: certificate has expired"):
                    await serve(dict(server="https://screen.example", token="private-device-token"),
                                FakeDesktop(), FakeTerminal(), sleep=sleep)
                connecting.assert_called_once()
                sleep.assert_not_awaited()

    def test_pair_certificate_failure_reports_host_reason_without_credentials(self):
        for error in (bad_certificate(), URLError(bad_certificate())):
            with patch.object(config, "urlopen", side_effect=error), \
                    patch.object(config, "save_config") as saving, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exiting:
                    cli.main(["pair", "https://screen.example", "pair-code"])
                self.assertEqual(exiting.exception.code, 1)
                self.assertIn("screen.example: certificate has expired", output.getvalue())
                self.assertNotIn("pair-code", output.getvalue())
                saving.assert_not_called()

    async def test_run_cli_prints_certificate_diagnostic_and_exits(self):
        message = certificate_failure(bad_certificate(), "https://screen.example")
        with patch.object(desktop, "Desktop", return_value=Mock(scale=1)), \
                patch.object(cli, "load_config", return_value={}), \
                patch("partyline_helper.terminal.Terminal"), \
                patch("partyline_helper.links.claim_run", return_value=True), \
                patch("partyline_helper.consent_dialog.notify"), \
                patch("partyline_helper.client.serve",
                      new=AsyncMock(side_effect=CertificateError(message))), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exiting:
                await asyncio.to_thread(cli.main, ["run"])
            self.assertEqual(exiting.exception.code, 1)
            self.assertIn(message, output.getvalue())

    def test_other_network_errors_are_not_certificate_failures(self):
        self.assertIsNone(certificate_failure(URLError("connection refused"), "https://screen.example"))
        error = OSError("outer")
        error.__cause__ = bad_certificate()
        self.assertIn("certificate has expired", certificate_failure(error, "screen.example"))
        error.__cause__ = error
        self.assertIsNone(certificate_failure(error, "screen.example"))


class CaptureReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.socket = FakeSocket()
        self.clock, self.term = ManualTime(), FakeTerminal()
        self.session = Session(self.socket, self.desktop, self.term, "desktop",
                               clock=self.clock, sleep=self.clock.sleep)

    async def asyncTearDown(self):
        await self.session.stop(notify=False)

    async def test_preview_size_and_rate_are_bounded_per_monitor_across_reconnects(self):
        self.desktop.image = Image.new("RGB", (2000, 1000), "white")
        monitors = [dict(id=1, **REGION), dict(id=2, **REGION)]
        self.desktop.monitors = lambda: monitors
        preview = dict(type="get_preview", request_id="first", monitor_id=1, long_edge=1280)
        await self.session.dispatch(preview)
        self.assertEqual(self.socket.sent[0]["out_width"], 480)
        self.assertEqual(self.socket.sent[0]["out_height"], 240)
        await self.session.dispatch(dict(preview, request_id="blocked"))
        self.assertEqual(len(self.desktop.grabs), 1)
        self.assertEqual(self.socket.sent[-1]["type"], "error")
        self.assertEqual(self.socket.sent[-1]["request_id"], "blocked")
        await self.session.dispatch(dict(preview, monitor_id=2))
        self.assertEqual(len(self.desktop.grabs), 2)
        reconnected = Session(self.socket, self.desktop, FakeTerminal(), "desktop",
                              preview_times=self.session.preview_times,
                              clock=self.clock, sleep=self.clock.sleep)
        await reconnected.dispatch(preview)
        self.assertEqual(len(self.desktop.grabs), 2)
        self.clock.advance(3)
        await reconnected.dispatch(preview)
        self.assertEqual(len(self.desktop.grabs), 3)
        self.assertEqual(self.socket.sent[-2]["type"], "preview")

    async def test_snap_refusal_precedes_capture_and_serializes_concurrent_requests(self):
        req = request()
        req["max_fps"] = 1
        await self.session.dispatch(req)
        await self.socket.next("frame")
        await self.term.waiting.get()
        async with self.session.frame_lock:
            pass
        first_grabs = len(self.desktop.grabs)
        first_time = self.session.last_frame_at
        await self.session.dispatch(dict(type="snap", share_id="share", request_id="too-soon"))
        self.assertEqual(len(self.desktop.grabs), first_grabs)
        self.assertEqual(self.socket.sent[-1]["type"], "error")
        self.assertEqual(self.socket.sent[-1]["request_id"], "too-soon")
        self.assertEqual(self.session.last_frame_at, first_time)
        self.clock.advance(1)
        await asyncio.gather(*(self.session.dispatch(dict(type="snap", share_id="share", request_id=str(i)))
                               for i in range(5)))
        frames = [m for m in self.socket.sent if isinstance(m, dict) and m["type"] == "frame"]
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[-1]["request_id"], "0")
        self.assertEqual(frames[-1]["ts_ms"], 1000)
        self.assertEqual(len(self.desktop.grabs), first_grabs + 1)

    async def test_snap_during_acceptance_has_initialized_timestamp_and_does_not_capture(self):
        paused, resume = asyncio.Event(), asyncio.Event()
        class Socket(FakeSocket):
            async def send(self, value):
                if isinstance(value, str) and json.loads(value)["type"] == "share_accepted":
                    paused.set()
                    await resume.wait()
                await super().send(value)
        socket = Socket()
        term = FakeTerminal()
        session = Session(socket, self.desktop, term, "desktop",
                          clock=self.clock, sleep=self.clock.sleep)
        await session.dispatch(request())
        try:
            await paused.wait()
            self.assertLessEqual(session.started, self.clock())
            await session.dispatch(dict(type="snap", share_id="share", request_id="early"))
            self.assertFalse(self.desktop.grabs)
            self.assertFalse(session.accepted)
            resume.set()
            await socket.next("frame")
            await term.waiting.get()
            self.assertEqual(socket.sent[0]["type"], "share_accepted")
            self.assertGreaterEqual(socket.sent[1]["ts_ms"], 0)
        finally:
            await session.stop(notify=False)


class ConsentReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = ManualTime()
        self.terminal = terminal.Terminal(clock=self.clock, sleep=self.clock.sleep, read_stdin=False)

    async def test_terminal_metadata_cannot_forge_lines_or_control_sequences(self):
        req = request()
        req["requested_by"] = "\x1b[2J\x1b]0;forged title\x07Person\r\nForged prompt\x00" + "x" * 200
        req["region"]["extra"] = "\nShare a different screen? [y/N]\x1b[2J"
        req["line_name"] = "\x1b[31mLine\x1b[0m\n\r\u202e" + "z" * 200
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(await self.terminal.consent(req, yes=True))
        rendered = output.getvalue()
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("forged title", rendered)
        self.assertNotIn("\r", rendered)
        self.assertNotIn("\u202e", rendered)
        lines = rendered.strip().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[-1], f"OS region: {REGION}")
        self.assertNotIn("extra", rendered)
        self.assertNotIn("different screen", rendered)
        self.assertLessEqual(len(lines[1].removeprefix("Requested by: ")), 120)
        self.assertLessEqual(len(lines[2].removeprefix("Line: ")), 120)

    async def test_every_prompt_ignores_input_for_its_first_second(self):
        for index in range(2):
            with self.subTest(prompt=index):
                pending = asyncio.create_task(self.terminal.consent(request(), timeout=60))
                self.assertEqual(await self.clock.sleep_calls.get(), 1)
                self.terminal.lines.put("y")
                self.clock.advance(.5)
                await checkpoint()
                self.assertFalse(pending.done())
                self.clock.advance(.5)
                self.assertEqual(await self.clock.sleep_calls.get(), 59)
                self.assertTrue(self.terminal.lines.empty())
                self.assertFalse(pending.done())
                self.terminal.lines.put("n")
                self.clock.advance(.05)
                self.assertFalse(await pending)
        pending = asyncio.create_task(self.terminal.consent(request(), timeout=60))
        await self.clock.sleep_calls.get()
        self.clock.advance(60)
        self.assertFalse(await pending)

    async def test_pending_prompt_declines_new_share_without_changing_consent_target(self):
        socket, desktop = FakeSocket(), FakeDesktop()
        session = Session(socket, desktop, self.terminal, "desktop", clock=self.clock, sleep=self.clock.sleep)
        original = request()
        original["share_id"] = "original"
        other = request()
        other.update(share_id="bait", line_name="bait line", requested_by="bait requester",
                     region=dict(x=0, y=0, width=100, height=100))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            await session.dispatch(original)
            worker = session.worker
            try:
                await self.clock.sleep_calls.get()
                await session.dispatch(other)
                self.assertEqual(await socket.next("share_declined"),
                                 dict(type="share_declined", share_id="bait", reason="prompt pending"))
                self.assertIs(session.worker, worker)
                self.assertEqual(session.pending_id, "original")
                self.assertNotIn("bait", output.getvalue())
                self.assertFalse(desktop.grabs)
                self.clock.advance(1)
                await self.clock.sleep_calls.get()
                self.terminal.lines.put("y")
                self.clock.advance(.05)
                self.assertEqual((await socket.next("share_accepted"))["share_id"], "original")
                self.assertEqual(await desktop.captured.get(), REGION)
                frame = await socket.next("frame")
                self.assertEqual(frame["share_id"], "original")
                self.assertEqual(frame["region"], REGION)
            finally:
                await session.stop(notify=False)


class PlatformReviewTests(unittest.TestCase):
    def test_wayland_display_without_session_type_is_refused(self):
        with patch.object(desktop.sys, "platform", "linux"), \
                patch.dict(os.environ, XDG_SESSION_TYPE="", WAYLAND_DISPLAY="wayland-0"):
            with self.assertRaisesRegex(RuntimeError, "Wayland is not supported yet"):
                desktop.prepare()

    def test_screen_recording_uses_bool_and_pointer_does_not_require_accessibility(self):
        core = Mock()
        core.CGPreflightScreenCaptureAccess.return_value = True
        capture = Mock()
        with patch.object(desktop.sys, "platform", "darwin"), \
                patch.object(desktop.ctypes, "CDLL", return_value=core) as library, \
                patch.dict("sys.modules", {"mss": SimpleNamespace(mss=lambda: capture),
                                          "pynput.mouse": SimpleNamespace(Controller=Mock)}), \
                patch("partyline_helper.retina.scale_factor", return_value=1), \
                patch("partyline_helper.retina.pointer_y_offset", return_value=0):
            obj = desktop.Desktop()
            self.assertIs(core.CGPreflightScreenCaptureAccess.restype, ctypes.c_bool)
            library.assert_called_once_with("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
            obj.close()

    def test_missing_extra_is_actionable(self):
        with patch.object(desktop, "Desktop", side_effect=ModuleNotFoundError("mss")), \
                patch("partyline_helper.links.claim_run", return_value=True), \
                patch("partyline_helper.consent_dialog.notify"), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit):
                cli.main(["run"])
            self.assertIn("uv sync --extra helper", output.getvalue())
