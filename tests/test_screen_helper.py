"""Native helper protocol tests never access a real screen or pointer."""
import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from websockets.asyncio.server import serve as websocket_server
from websockets.http11 import Response
from websockets.datastructures import Headers

from partyline_helper import cli, config, desktop, images, terminal
from partyline_helper.client import Session, bounded
from tests.screen_helper_fakes import (
    FakeDesktop, FakeSocket, FakeTerminal, ManualTime, MONITOR, REGION, checkpoint, request, serve,
)


class ConfigTests(unittest.TestCase):
    def test_pair_permissions_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config" / "helper.json"
            response = io.BytesIO(b'{"device_id":"device","token":"secret"}')
            with patch.object(config, "config_path", return_value=path), \
                    patch.object(config, "urlopen", return_value=response) as opening:
                config.pair("https://screen.example", "code", "desktop")
                self.assertEqual(config.load_config()["token"], "secret")
                self.assertEqual(json.loads(opening.call_args.args[0].data)["device_name"], "desktop")
                if os.name != "nt":
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                config.save_config({"token": "replacement"})
                self.assertEqual(config.load_config(), {"token": "replacement"})
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_origins(self):
        self.assertEqual(config.server_url("screen.example"), "https://screen.example")
        self.assertEqual(config.server_url("HTTPS://screen.example/"), "https://screen.example")
        for value in ("ftp://bad", "https://a/x", "https://u:p@a", "https://a?q=1", "https://a#x"):
            with self.assertRaises(ValueError):
                config.server_url(value)
        with self.assertWarns(UserWarning):
            self.assertEqual(config.server_url("http://192.168.1.2/"), "http://192.168.1.2")
        with self.assertRaises(ValueError):
            config.server_url("http://8.8.8.8")

    def test_paths(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom"}):
            if os.name != "nt":
                self.assertEqual(config.config_path(), Path("/custom/partyline/helper.json"))


class ImageTests(unittest.TestCase):
    def test_gate_and_encoding(self):
        a = images.thumbnail(Image.new("RGB", (300, 200), "white"))
        b = images.thumbnail(Image.new("RGB", (300, 200), "black"))
        self.assertTrue(images.changed(None, a, .02))
        self.assertFalse(images.changed(a, a, .02))
        self.assertTrue(images.changed(a, b, .02))
        data, width, height, mime = images.encode(Image.new("RGB", (2000, 1000)), 1280)
        self.assertEqual((width, height, mime), (1280, 640, "image/webp"))
        self.assertLessEqual(len(data), images.MAX_BYTES)

    def test_fallback_and_size_cap(self):
        original = Image.Image.save

        def saving(image, output, fmt, **kwargs):
            if fmt == "WEBP":
                raise OSError("no WebP")
            return original(image, output, fmt, **kwargs)

        with patch.object(Image.Image, "save", saving), patch.object(images, "MAX_BYTES", 700):
            data, width, height, mime = images.encode(Image.effect_noise((512, 512), 100), 512)
        self.assertLessEqual(len(data), 700)
        self.assertLess(width, 512)
        self.assertEqual(mime, "image/jpeg")
        with patch.object(images, "MAX_BYTES", 1), self.assertRaises(ValueError):
            images.encode(Image.new("RGB", (1, 1)), 10)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.terminal = FakeTerminal()
        self.socket = FakeSocket()
        self.clock = ManualTime()
        self.session = Session(self.socket, self.desktop, self.terminal, "desktop",
                               clock=self.clock, sleep=self.clock.sleep)

    async def asyncTearDown(self):
        await self.session.stop(notify=False)

    async def accepted(self):
        await self.session.dispatch(request())
        await self.socket.next("frame")
        await self.terminal.waiting.get()

    async def test_capture_waits_for_consent_and_remote_stop(self):
        pending = asyncio.get_running_loop().create_future()
        self.terminal.answer = pending
        await self.session.dispatch(request())
        await self.terminal.prompts.get()
        self.assertFalse(self.desktop.grabs)
        pending.set_result(True)
        await self.desktop.grabbed.wait()
        await self.socket.next("frame")
        await self.terminal.waiting.get()
        self.assertEqual(self.socket.sent[0]["type"], "share_accepted")
        frame = self.socket.sent[1]
        self.assertEqual(frame["pointer"], dict(x=-20, y=30, visible=True))
        self.assertEqual(frame["region"], REGION)
        await self.session.dispatch(dict(type="stop_share", share_id="share"))
        count = len(self.desktop.grabs)
        self.clock.advance(10)
        self.terminal.lines.put_nowait(None)
        await checkpoint()
        self.assertEqual(len(self.desktop.grabs), count)
        self.assertEqual(self.socket.sent[-1]["type"], "share_stopped")

    async def test_decline_and_pending_cancel(self):
        self.terminal.answer = False
        await self.session.start(request())
        self.assertEqual(self.socket.sent[-1]["type"], "share_declined")
        self.assertFalse(self.desktop.grabs)
        await self.terminal.prompts.get()
        self.terminal.answer = asyncio.get_running_loop().create_future()
        await self.session.dispatch(request())
        await self.terminal.prompts.get()
        await self.session.dispatch(dict(type="stop_share", share_id="share"))
        self.assertFalse(self.desktop.grabs)

    async def test_change_pointer_snap_preview(self):
        await self.accepted()
        await self.session.stop(notify=False)
        self.session.share = request()
        self.session.accepted = True
        self.session.last_frame_at = None
        self.session.validate(self.session.share)
        self.socket.sent.clear()
        await self.session.frame()
        self.assertEqual(self.socket.sent, [])
        self.desktop.position = (300, 10)
        await self.session.frame()
        self.assertFalse(self.socket.sent[0]["pointer"]["visible"])
        self.socket.sent.clear()
        self.desktop.image = Image.new("RGB", (200, 100), "black")
        self.session.last_frame_at = None
        await self.session.frame()
        self.assertEqual(self.socket.sent[0]["type"], "frame")
        self.socket.sent.clear()
        self.session.last_frame_at = None
        await self.session.dispatch(dict(type="snap", share_id="share", request_id="snap"))
        self.assertEqual(self.socket.sent[0]["request_id"], "snap")
        await self.session.dispatch(dict(type="get_preview", request_id="pick", monitor_id=1, long_edge=80))
        self.assertEqual(self.socket.sent[-2]["type"], "preview")
        self.assertEqual(self.socket.sent[-2]["out_width"], 80)
        self.assertIsInstance(self.socket.sent[-1], bytes)
        await self.session.dispatch(dict(type="ping"))
        self.assertEqual(self.socket.sent[-1]["type"], "pong")

    async def test_local_stop_and_replace(self):
        await self.accepted()
        await self.terminal.lines.put("s")
        await self.socket.next("share_stopped")
        self.assertIsNone(self.session.share)
        self.assertEqual(self.socket.sent[-1]["reason"], "local")
        await self.accepted()
        await self.session.dispatch(request())
        stopped = await self.socket.next("share_stopped")
        self.assertEqual(stopped["reason"], "replaced")
        await self.socket.next("frame")
        await self.terminal.waiting.get()

    async def test_invalid_requests_capture_error(self):
        for field, value in (("width", 0), ("width", 32769), ("x", -101), ("y", 1.5)):
            req = request()
            req["region"][field] = value
            await self.session.start(req)
            self.assertEqual(self.socket.sent[-1]["type"], "share_declined")
        req = request()
        req["region"].update(width=20000, height=20000)
        await self.session.start(req)
        self.assertEqual(self.socket.sent[-1]["type"], "share_declined")
        with self.assertRaises(ValueError):
            bounded(float("nan"), 1, 0, 30)
        with patch.object(self.desktop, "grab", side_effect=RuntimeError("permission")):
            await self.session.start(request())
        self.assertEqual(self.socket.sent[-1]["type"], "share_stopped")
        await self.session.frame()  # no accepted share

    async def test_heartbeat(self):
        heartbeat = asyncio.create_task(self.session.heartbeat())
        self.assertEqual(await self.clock.sleep_calls.get(), 15)
        self.clock.advance(15)
        await self.socket.next("ping")
        self.assertEqual(await self.clock.sleep_calls.get(), 15)
        self.clock.advance(30)
        await heartbeat
        self.assertEqual(self.socket.closed["code"], 1011)
        self.assertEqual([m["type"] for m in self.socket.sent], ["ping"])


class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_accept_decline_timeout_yes(self):
        clock = ManualTime()
        term = terminal.Terminal(clock=clock, sleep=clock.sleep, read_stdin=False)
        with patch("sys.stdin", io.StringIO("y\ns\n")):
            term._read()
        self.assertEqual(await term.read(.1), "y")
        self.assertEqual(await term.read(.1), "s")
        reading = asyncio.create_task(term.read(.1))
        await clock.sleep_calls.get()
        clock.advance(.1)
        self.assertIsNone(await reading)
        term.lines.put("stale")
        self.assertTrue(await term.consent(request(), yes=True))
        self.assertTrue(term.lines.empty())
        for answer in ("y", "n"):
            with patch.object(term, "read", new=AsyncMock(return_value=answer)):
                consenting = asyncio.create_task(term.consent(request()))
                self.assertEqual(await clock.sleep_calls.get(), 1)
                clock.advance(1)
                self.assertEqual(await consenting, answer == "y")
        consenting = asyncio.create_task(term.consent(request(), timeout=60))
        await clock.sleep_calls.get()
        clock.advance(60)
        self.assertFalse(await consenting)
        with patch("threading.Thread") as thread:
            terminal.Terminal()
            self.assertTrue(thread.call_args.kwargs["daemon"])


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pair_hello_preview_consent_frames_snap_stop(self):
        fake_desktop = FakeDesktop()
        term = FakeTerminal()
        clock, prompt_clock = ManualTime(), ManualTime()
        local = terminal.Terminal(clock=prompt_clock, sleep=prompt_clock.sleep, read_stdin=False)

        async def consent(req, yes):
            consenting = asyncio.create_task(local.consent(req, yes))
            await prompt_clock.sleep_calls.get()
            prompt_clock.advance(1)
            await prompt_clock.sleep_calls.get()
            local.lines.put("y")
            prompt_clock.advance(.05)
            return await consenting
        term.consent = AsyncMock(side_effect=consent)
        completed = asyncio.Event()
        seen = []

        async def receive(ws, kind):
            while True:
                raw = await ws.recv()
                if isinstance(raw, bytes):
                    continue
                data = json.loads(raw)
                seen.append(data)
                if data["type"] == kind:
                    if kind in ("frame", "preview"):
                        self.assertIsInstance(await ws.recv(), bytes)
                    return data

        async def claim(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            if head.startswith(b"GET "):
                # One origin serves HTTP pairing and proxies upgrades to websockets.
                upstream, outgoing = await asyncio.open_connection("127.0.0.1", port)
                outgoing.write(head)
                await outgoing.drain()

                async def relay(source, destination):
                    try:
                        while chunk := await source.read(65536):
                            destination.write(chunk)
                            await destination.drain()
                    finally:
                        destination.close()
                await asyncio.gather(relay(reader, outgoing), relay(upstream, writer))
                return
            self.assertTrue(head.startswith(b"POST /api/screen/pair/claim "))
            length = next(int(line.split(b":")[1]) for line in head.split(b"\r\n")
                          if line.lower().startswith(b"content-length:"))
            body = json.loads(await reader.readexactly(length))
            self.assertEqual(body["code"], "code")
            payload = b'{"device_id":"device","token":"secret"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode() +
                         b"\r\nConnection: close\r\n\r\n" + payload)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async def handler(ws):
            self.assertEqual(ws.request.headers["Authorization"], "Bearer secret")
            hello = await receive(ws, "hello")
            self.assertEqual(hello["monitors"], [MONITOR])
            self.assertEqual(hello["protocol"], 1)
            await ws.send(json.dumps(dict(type="get_preview", request_id="pick", monitor_id=1, long_edge=64)))
            await receive(ws, "preview")
            await ws.send(json.dumps(request()))
            await receive(ws, "share_accepted")
            frame = await receive(ws, "frame")
            self.assertEqual(frame["pointer"]["x"], -20)
            await term.waiting.get()
            clock.advance(1)
            await ws.send(json.dumps(dict(type="snap", share_id="share", request_id="fresh")))
            frame = await receive(ws, "frame")
            self.assertEqual(frame["request_id"], "fresh")
            await ws.send(json.dumps(dict(type="stop_share", share_id="share")))
            await receive(ws, "share_stopped")
            await ws.close(code=4001, reason="revoked")
            completed.set()

        async with websocket_server(handler, "127.0.0.1", 0, ping_interval=None) as server, \
                await asyncio.start_server(claim, "127.0.0.1", 0) as http:
            port = server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as tmp, \
                    patch.object(config, "config_path", return_value=Path(tmp)/"c"):
                with self.assertWarns(UserWarning):
                    await asyncio.to_thread(config.pair, f"http://127.0.0.1:{http.sockets[0].getsockname()[1]}",
                                           "code", "desktop")
                paired = config.load_config()
                with self.assertWarns(UserWarning):
                    await serve(paired, fake_desktop, term, clock=clock)
            await completed.wait()
            self.assertTrue(term.consent.called)

    async def test_reconnect_and_revoke(self):
        calls = []

        async def handler(ws):
            calls.append(json.loads(await ws.recv()))
            await ws.close(code=1011 if len(calls) == 1 else 1008)

        async with websocket_server(handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            sleep = AsyncMock()
            with self.assertWarns(UserWarning):
                await serve(dict(server=f"http://127.0.0.1:{port}", token="secret",
                                 device_name="desktop"), FakeDesktop(), FakeTerminal(), sleep=sleep)
            self.assertEqual(len(calls), 2)
            sleep.assert_awaited_once_with(1)

    async def test_http_revoke(self):
        async def reject(connection, req):
            return Response(401, "Unauthorized", Headers(), b"revoked")
        async with websocket_server(lambda ws: None, "127.0.0.1", 0, process_request=reject,
                                    ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            with self.assertWarns(UserWarning):
                await serve(dict(server=f"http://127.0.0.1:{port}", token="secret",
                                 device_name="desktop"), FakeDesktop(), FakeTerminal())


class PlatformTests(unittest.TestCase):
    def test_wayland(self):
        with patch.object(desktop.sys, "platform", "linux"), \
                patch.dict(os.environ, XDG_SESSION_TYPE="wayland"):
            with self.assertRaisesRegex(RuntimeError, "Wayland is not supported yet"):
                desktop.prepare()

    def test_windows_dpi(self):
        windll = Mock()
        windll.user32.SetProcessDpiAwarenessContext.return_value = 0
        with patch.object(desktop.sys, "platform", "win32"), patch.object(desktop.ctypes, "windll", windll,
                                                                         create=True):
            desktop.prepare()
        windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)

    def test_backend(self):
        capture = Mock()
        capture.monitors = [{}, dict(left=-100, top=0, width=200, height=100)]
        capture.grab.return_value = SimpleNamespace(size=(2, 2), rgb=b'\xff' * 12)
        mouse = Mock(position=(-1, 2))
        with patch.dict("sys.modules", {"mss": SimpleNamespace(mss=Mock(return_value=capture)),
                                       "pynput.mouse": SimpleNamespace(Controller=lambda: mouse)}), \
                patch.object(desktop, "prepare"), patch.object(desktop.sys, "platform", "linux"):
            obj = desktop.Desktop()
            self.assertEqual(obj.monitors()[0]["x"], -100)
            self.assertEqual(obj.pointer(), (-1, 2))
            self.assertEqual(obj.grab(REGION).size, (2, 2))
            obj.close()
            capture.close.assert_called_once()

    def test_mac_permissions(self):
        core = Mock()
        core.CGPreflightScreenCaptureAccess.return_value = False
        with patch.object(desktop.sys, "platform", "darwin"), patch.object(desktop.ctypes, "CDLL",
                                                                          side_effect=[core]):
            with self.assertRaisesRegex(RuntimeError, "Screen Recording"):
                desktop.Desktop()
        obj = desktop.Desktop.__new__(desktop.Desktop)
        obj.capture = Mock()
        obj.scale = 1
        obj.capture.grab.return_value = SimpleNamespace(size=(1, 1), rgb=b'\x00'*3)
        with patch.object(desktop.sys, "platform", "darwin"):
            with self.assertRaisesRegex(RuntimeError, "Blank capture"):
                obj.grab(REGION)


class CliTests(unittest.TestCase):
    def test_pair_prints_both_full_run_commands(self):
        out = io.StringIO()
        with patch.object(cli, "pair"), contextlib.redirect_stdout(out):
            cli.main(["pair", "https://screen.example", "code"])
        text = out.getvalue()
        self.assertIn("uvx --from 'partyline[helper] @ git+https://github.com/High-AiQ/partyline.git' "
                      "partyline-helper run", text)
        self.assertIn("uv run --extra helper partyline-helper run", text)
        self.assertIn("Answer y to each share prompt", text)

    def test_commands(self):
        with patch.object(cli, "pair") as pairing:
            cli.main(["pair", "https://screen.example", "code", "--name", "desk"])
            pairing.assert_called_once_with("https://screen.example", "code", "desk")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(cli, "config_path", return_value=Path(tmp)/"c"):
            cli.main(["unpair"])
        obj = Mock()
        obj.monitors.return_value = [MONITOR]
        with patch.object(desktop, "Desktop", return_value=obj):
            cli.main(["monitors"])
            obj.close.assert_called_once()
        with patch.object(desktop, "Desktop", side_effect=RuntimeError("Wayland is not supported yet")):
            with self.assertRaises(SystemExit):
                cli.main(["run"])
        with patch.object(cli, "pair", side_effect=ValueError("secret")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                cli.main(["pair", "bad", "code"])
            self.assertNotIn("secret", out.getvalue())


class RetinaTests(unittest.TestCase):
    def test_scale_and_mixed_guard(self):
        from partyline_helper.retina import scale_factor
        quartz = Mock()
        quartz.CGGetActiveDisplayList.return_value = (0, [1, 2], 2)
        quartz.CGDisplayBounds.return_value = SimpleNamespace(size=SimpleNamespace(width=100))
        quartz.CGDisplayPixelsWide.return_value = 200
        with patch.dict("sys.modules", Quartz=quartz):
            self.assertEqual(scale_factor(), 2)
            quartz.CGDisplayPixelsWide.side_effect = [100, 200]
            with self.assertRaisesRegex(RuntimeError, "Mixed Retina"):
                scale_factor()
            quartz.CGGetActiveDisplayList.return_value = (1, [], 0)
            with self.assertRaises(RuntimeError):
                scale_factor()

    def test_pynput_retina_vertical_origin(self):
        from partyline_helper.retina import pointer_y_offset
        quartz = Mock()
        quartz.CGDisplayBounds.return_value = SimpleNamespace(size=SimpleNamespace(height=900))
        quartz.CGDisplayPixelsHigh.return_value = 1800
        with patch.dict("sys.modules", Quartz=quartz):
            self.assertEqual(pointer_y_offset(), -900)
        obj = desktop.Desktop.__new__(desktop.Desktop)
        obj.mouse = Mock(position=(100, 1000))
        obj.scale = 2
        obj.pointer_y_offset = -900
        self.assertEqual(obj.pointer(), (200, 200))

    @patch.object(desktop.sys, "platform", "darwin")
    def test_backing_pixel_coordinates(self):
        obj = desktop.Desktop.__new__(desktop.Desktop)
        obj.capture = Mock()
        obj.capture.monitors = [{}, dict(left=-100, top=0, width=100, height=50)]
        obj.capture.grab.return_value = SimpleNamespace(size=(20, 20), rgb=b'\xff'*1200)
        obj.mouse = Mock(position=(-50, 10))
        obj.pointer_y_offset = 0
        obj.scale = 2
        self.assertEqual(obj.monitors()[0], dict(id=1, x=-200, y=0, width=200, height=100,
                                               scale=2, primary=False))
        self.assertEqual(obj.pointer(), (-100, 20))
        obj.grab(dict(x=-200, y=0, width=40, height=40))
        obj.capture.grab.assert_called_once_with(dict(left=-100, top=0, width=20, height=20))


class ExtraHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_cli(self):
        fake = Mock()
        with patch.object(desktop, "Desktop", return_value=fake), \
                patch.object(cli, "load_config", return_value={}), \
                patch("partyline_helper.terminal.Terminal"), \
                patch("partyline_helper.client.serve", new=AsyncMock()) as serving:
            # CLI owns its own loop, so invoke it outside this test's event loop.
            await asyncio.to_thread(cli.main, ["run", "--yes"])
            self.assertTrue(serving.call_args.args[-1])
        with patch.object(desktop, "Desktop", side_effect=KeyboardInterrupt):
            cli.main(["run"])

    async def test_invalid_json_and_unknown_monitor(self):
        async def handler(ws):
            await ws.recv()
            await ws.send("{")
            self.assertEqual(json.loads(await ws.recv())["type"], "error")
            await ws.send(json.dumps(dict(type="get_preview", monitor_id=100, request_id="bad")))
            self.assertEqual(json.loads(await ws.recv()),
                             dict(type="error", request_id="bad",
                                  message="Invalid request or capture failed; see local terminal"))
            await ws.close(code=1008)
        async with websocket_server(handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            with self.assertWarns(UserWarning):
                await serve(dict(server=f"http://127.0.0.1:{port}", token="secret"),
                            FakeDesktop(), FakeTerminal())

    async def test_backoff_caps_without_handshake(self):
        delays = []
        async def sleep(delay):
            delays.append(delay)
            if len(delays) == 9:
                raise asyncio.CancelledError
        with patch("partyline_helper.client.connect", side_effect=OSError), \
                self.assertRaises(asyncio.CancelledError):
            await serve(dict(server="https://screen.example", token="secret"), FakeDesktop(), FakeTerminal(),
                        sleep=sleep)
        self.assertEqual(delays, [1, 2, 4, 8, 16, 32, 60, 60, 60])

    def test_desktop_errors_and_windows_monitor(self):
        obj = desktop.Desktop.__new__(desktop.Desktop)
        obj.scale = 1
        obj.capture = Mock()
        obj.capture.grab.side_effect = Exception("backend failure")
        with self.assertRaisesRegex(RuntimeError, "Desktop capture failed"):
            obj.grab(REGION)
        obj.capture.monitors = [{}, dict(left=0, top=0, width=100, height=100)]
        windll = Mock()
        windll.user32.MonitorFromPoint.return_value = 123
        def dpi(handle, kind, dx, dy):
            dx._obj.value = 144
        windll.shcore.GetDpiForMonitor.side_effect = dpi
        with patch.object(desktop.sys, "platform", "win32"), \
                patch.object(desktop.ctypes, "windll", windll, create=True):
            self.assertEqual(obj.monitors()[0]["scale"], 1.5)


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ctrl_c_cancellation_sends_stopped(self):
        class Socket(FakeSocket):
            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Future()
        socket = Socket()
        clock, term = ManualTime(), FakeTerminal()
        session = Session(socket, FakeDesktop(), term, "desktop", clock=clock, sleep=clock.sleep)
        running = asyncio.create_task(session.run())
        await socket.sent_event.wait()
        self.assertEqual(socket.sent[0]["type"], "hello")
        await session.dispatch(request())
        await socket.next("frame")
        await term.waiting.get()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertEqual(socket.sent[-1]["type"], "share_stopped")
        self.assertEqual(socket.sent[-1]["reason"], "disconnected")
        self.assertIsNone(session.share)


class DisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_ends_active_capture(self):
        fake = FakeDesktop()
        clock, term = ManualTime(), FakeTerminal()
        accepted = asyncio.Event()
        async def handler(ws):
            await ws.recv()
            await ws.send(json.dumps(request()))
            self.assertEqual(json.loads(await ws.recv())["type"], "share_accepted")
            self.assertEqual(json.loads(await ws.recv())["type"], "frame")
            await ws.recv()
            accepted.set()
            await ws.close(code=1008)
        async with websocket_server(handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            with self.assertWarns(UserWarning):
                await serve(dict(server=f"http://127.0.0.1:{port}", token="secret"), fake, term, clock=clock)
            self.assertTrue(accepted.is_set())
            count = len(fake.grabs)
            clock.advance(60)
            term.lines.put_nowait(None)
            await checkpoint()
            self.assertEqual(len(fake.grabs), count)


class AtomicFrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_preserves_metadata_binary_pair(self):
        paused, resume = asyncio.Event(), asyncio.Event()
        class Socket(FakeSocket):
            async def send(self, value):
                await super().send(value)
                if isinstance(value, str) and json.loads(value)["type"] == "frame":
                    paused.set()
                    await resume.wait()
        socket = Socket()
        clock, term = ManualTime(), FakeTerminal()
        session = Session(socket, FakeDesktop(), term, "desktop", clock=clock, sleep=clock.sleep)
        await session.dispatch(request())
        await paused.wait()
        stopping = asyncio.create_task(session.stop())
        await checkpoint()
        resume.set()
        await stopping
        self.assertEqual(socket.sent[1]["type"], "frame")
        self.assertIsInstance(socket.sent[2], bytes)
        self.assertEqual(socket.sent[3]["type"], "share_stopped")
