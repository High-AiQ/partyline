"""The helper's add-on client (a real loopback server), the audit chain, and the consent checkbox plumbing."""
import asyncio
import base64
import contextlib
import io
import json
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from partyline_helper import consent_dialog, dialog_proc, tools_consent
from partyline_helper.status import Status
from partyline_helper.terminal import Terminal
from partyline_helper.tools_addon import SPECS, AddonClient, AddonError, spec_for
from partyline_helper.tools_audit import ToolAudit
from tests.screen_helper_fakes import ManualTime
from tests.test_helper_dialog import FakePopen, TkDialogProcessTests

SECRET = "s" * 64


class Addon(BaseHTTPRequestHandler):
    """A stand-in add-on: checks the bearer secret and the Host header like the real one does."""
    seen = []
    replies = {}

    def log_message(self, *args):
        pass

    def respond(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        Addon.seen.append((self.command, self.path, body, dict(self.headers)))
        if self.headers.get("Authorization") != "Bearer " + SECRET:
            status, data = 401, {"error": "bad secret"}
        else:
            status, data = Addon.replies.get(self.path, (200, {"ok": True}))
        raw = (b"x" * (2 * 1024 * 1024) if data == "huge" else data if isinstance(data, bytes)
               else json.dumps(data).encode())
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = respond


class AddonClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Addon)
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()
        Addon.seen, Addon.replies = [], {}
        self.spec = SPECS["blender"]
        self.write(self.server.server_address[1], SECRET)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def write(self, port, secret):
        (self.dir / self.spec.discovery).write_text(json.dumps({"port": port, "secret": secret}))

    def client(self):
        return AddonClient(self.spec, self.dir)

    async def test_requests_carry_the_secret_to_loopback_only(self):
        info = await self.client().info()
        self.assertEqual(info, {"ok": True})
        _, _, _, headers = Addon.seen[0]
        self.assertEqual(headers["Authorization"], "Bearer " + SECRET)
        self.assertTrue(headers["Host"].startswith("127.0.0.1:"))
        self.assertNotIn("Origin", headers)

    async def test_wrong_secret_is_refused_by_the_addon_and_reported(self):
        self.write(self.server.server_address[1], "wrong")
        with self.assertRaisesRegex(AddonError, "refused the connection"):
            await self.client().info()
        with self.assertRaisesRegex(AddonError, "bad secret"):
            await self.client().open_session("s", "agent", False)

    async def test_session_renew_call_cancel_and_close(self):
        client = self.client()
        Addon.replies["/session"] = (200, {"ok": True, "backup": "b.blend"})
        self.assertEqual((await client.open_session("s", "agent", True))["backup"], "b.blend")
        self.assertEqual(Addon.seen[-1][2], {"id": "s", "agent": "agent", "checker": True})
        self.assertIsNone(await client.renew("s"))
        Addon.replies["/session/renew"] = (410, {"ended": "lease"})
        self.assertEqual(await client.renew("s"), "lease")
        Addon.replies["/session/renew"] = (410, {"ended": "blender"})
        self.assertEqual(await client.renew("s"), "app")
        Addon.replies["/session/renew"] = (404, {})
        self.assertEqual(await client.renew("s"), "unknown")
        Addon.replies["/call"] = (200, {"ok": True, "stdout": "x"})
        done = await client.call("s", "c", "exec", {"code": "1"}, 5)
        self.assertEqual(done, {"result": {"ok": True, "stdout": "x"}})
        Addon.replies["/call"] = (409, {"busy": True})
        self.assertTrue((await client.call("s", "c", "exec", {}, 5))["busy"])
        Addon.replies["/call"] = (413, {"error": "too big"})
        self.assertEqual((await client.call("s", "c", "exec", {}, 5))["error"], "too big")
        await client.cancel("s", "c")
        await client.close_session("s")
        self.assertEqual(Addon.seen[-1][1], "/session/close")

    async def test_an_artifact_is_fetched_as_raw_bytes_and_errors_are_plain(self):
        client = self.client()
        Addon.replies["/artifact"] = (200, b"\x89PNG-bytes")
        self.assertEqual(await client.artifact("s", "a1"), b"\x89PNG-bytes")
        self.assertEqual(Addon.seen[-1][:3], ("POST", "/artifact", {"session": "s", "id": "a1"}))
        self.assertEqual(Addon.seen[-1][3]["Authorization"], "Bearer " + SECRET)
        Addon.replies["/artifact"] = (404, {"error": "unknown artifact"})
        with self.assertRaisesRegex(AddonError, "unknown artifact"):
            await client.artifact("s", "a1")
        Addon.replies["/artifact"] = (500, b"<html>")
        with self.assertRaisesRegex(AddonError, "answered HTTP 500"):
            await client.artifact("s", "a1")
        Addon.replies["/artifact"] = (200, b"x" * 100)
        with patch("partyline_helper.tools_addon.MAX_ARTIFACT", 10), \
                self.assertRaisesRegex(AddonError, "too large"):
            await client.artifact("s", "a1")

    async def test_missing_unreachable_and_oversized_are_clean_errors(self):
        empty = AddonClient(self.spec, self.dir / "nowhere")
        with self.assertRaisesRegex(AddonError, "enable Partyline Relay"):
            await empty.info()
        for bad in ({"port": "80", "secret": SECRET}, {"port": 0, "secret": SECRET},
                    {"port": 1, "secret": ""}):
            (self.dir / self.spec.discovery).write_text(json.dumps(bad))
            with self.assertRaises(AddonError):
                await self.client().info()
        (self.dir / self.spec.discovery).write_text("not json")
        with self.assertRaises(AddonError):
            await self.client().info()
        self.write(self.server.server_address[1], SECRET)
        Addon.replies["/status"] = (200, "huge")
        with self.assertRaisesRegex(AddonError, "too large"):
            await self.client().info()
        self.server.shutdown()
        self.server.server_close()
        self.write(self.server.server_address[1], SECRET)
        with self.assertRaisesRegex(AddonError, "not reachable"):
            await self.client().info()
        Addon.replies.pop("/status")
        self.assertIsNone(spec_for("paint"))
        self.assertIsNone(spec_for("../blender"))
        self.assertIsNone(spec_for(3))
        self.assertIs(spec_for("blender"), self.spec)


class AuditAndConsentTests(unittest.IsolatedAsyncioTestCase):
    def test_audit_chain_survives_restart_and_detects_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "audit.jsonl"
            first = ToolAudit(path, clock=lambda: 1.0)
            first.append("call", "s", "agent", "exec", "exec 4 bytes", "ünï")
            second = ToolAudit(path, clock=lambda: 2.0)  # a new helper process continues the chain
            second.append("event", "s", "agent", "session", "revoked")
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(rows[1]["prev"], rows[0]["hash"])
            self.assertEqual((rows[0]["code"], rows[0]["code_bytes"]), ("ünï", 5))
            path.write_text("garbage\n")
            third = ToolAudit(path)
            third.append("event", "s", "agent", "session", "after damage")
            self.assertEqual(json.loads(path.read_text().splitlines()[-1])["prev"], "")

    def test_consent_text_names_agent_file_backup_and_kill_switch(self):
        spec = SPECS["blender"]
        request = {"requested_by": "agent\x1b[2J", "line_name": "L", "checker": True}
        question, title, message = tools_consent.session_text(spec, request, {"file": "a.blend"})
        self.assertNotIn("\x1b", message + title)
        self.assertIn("a.blend", message)
        self.assertIn("Ctrl+Alt+Esc", message)
        self.assertIn("backup", message)
        self.assertIn("[y/N]", question)
        _, _, unsaved = tools_consent.session_text(spec, request, {})
        self.assertIn("unsaved", unsaved)

    async def test_ask_and_scope_wiring(self):
        spec = SPECS["blender"]
        seen = []

        class Term:
            async def ask_box(self, question, dialog=None, box=None):
                seen.append(box)
                return True, True

            async def ask(self, question, dialog=None):
                return True
        self.assertEqual(await tools_consent.ask(Term(), spec, {"checker": True}, {}), (True, True))
        self.assertEqual(await tools_consent.ask(Term(), spec, {"checker": False}, {}), (True, False))
        self.assertEqual(seen[0], tools_consent.CHECKER_BOX)
        self.assertIsNone(seen[1])
        self.assertTrue(await tools_consent.ask_scope(Term(), spec, {"requested_by": "a"}))


class CheckboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = ManualTime()

    def test_request_and_exit_codes_carry_the_box(self):
        request = dialog_proc.encode_request("T", "M", 5, box="Tick me", parent=1)
        self.assertEqual(json.loads(base64.urlsafe_b64decode(request))["box"], "Tick me")
        self.assertNotIn("box", json.loads(base64.urlsafe_b64decode(dialog_proc.encode_request("T", "M", 5))))
        for code, answer, ticked in ((0, True, False), (4, True, True), (1, False, False)):
            def popen(command, code=code, **options):
                return FakePopen(command, code, **options)
            handle = consent_dialog.ProcessDialog("T", "M", 5, popen, box="x")
            self.assertIs(handle.wait(), answer)
            self.assertIs(handle.checked, ticked)

    def test_tk_checkbox_is_returned_only_with_a_yes(self):
        class Var:
            def __init__(self, value=False):
                self.value = value

            def get(self):
                return self.value
        for press, tick, expected in (("Yes", True, [True]), ("Yes", False, [False]), ("No", True, [])):
            module, root = TkDialogProcessTests.fake_tk(None, press)
            module.BooleanVar = Var
            boxes = []

            def checkbutton(parent, variable, tick=tick, boxes=boxes, **kwargs):
                variable.value = tick
                boxes.append(kwargs["text"])
                return types.SimpleNamespace(pack=lambda **k: None)
            module.Checkbutton = checkbutton
            ticked = []
            with patch.dict(sys.modules, {"tkinter": module}):
                dialog_proc.tk_ask("T", "M", 5, box="Tick me", ticked=ticked)
            self.assertEqual((boxes, ticked), (["Tick me"], expected))
        module, _ = TkDialogProcessTests.fake_tk(None, "OK")
        with patch.dict(sys.modules, {"tkinter": module}):  # a notice never shows a box
            self.assertTrue(dialog_proc.tk_ask("T", "M", 5, "info", box="x"))

    def test_main_returns_four_for_yes_with_the_box(self):
        request = dialog_proc.encode_request("T", "M", 5, box="x", parent=3)
        with patch.object(dialog_proc, "ask", lambda *a: a[5].append(True) or True):
            self.assertEqual(dialog_proc.main([request], lambda pid: None), 4)
        with patch.object(dialog_proc, "ask", lambda *a: True):
            self.assertEqual(dialog_proc.main([request], lambda pid: None), 0)
        with patch.object(dialog_proc, "ask", lambda *a: False):
            self.assertEqual(dialog_proc.main([request], lambda pid: None), 1)

    def test_ask_without_tk_ignores_the_box(self):
        with patch.dict(sys.modules, {"tkinter": None}), patch.object(dialog_proc.os, "name", "posix"):
            self.assertFalse(dialog_proc.ask("T", "M", 5, "ask", "box", []))

    async def run_box(self, handle_factory, box="Tick", timeout=60):
        def backend(title, message, remaining, box=None):
            return handle_factory()
        task = asyncio.create_task(consent_dialog.confirm_with_box("T", "M", box, timeout, backend,
                                                                   self.clock.sleep))
        await self.clock.sleep_calls.get()
        self.clock.advance(1)
        await self.clock.sleep_calls.get()
        return task

    async def test_confirm_with_box_reports_both_answers(self):
        class Handle:
            def __init__(self, yes, ticked):
                self.yes, self.checked = yes, ticked

            def wait(self):
                return self.yes

            def close(self):
                pass
        for yes, ticked, expected in ((True, True, (True, True)), (True, False, (True, False)),
                                      (False, True, (False, False))):
            task = await self.run_box(lambda yes=yes, ticked=ticked: Handle(yes, ticked))
            self.assertEqual(await task, expected)
        with patch.object(consent_dialog, "default_backend", return_value=None):
            self.assertEqual(await consent_dialog.confirm_with_box("T", "M", "b"), (False, False))

        def broken(*args, **kwargs):
            raise OSError("no display")
        self.assertEqual(await consent_dialog.confirm_with_box("T", "M", "b", 5, broken, _instant),
                         (False, False))

    async def test_silence_declines_with_the_box_unticked(self):
        class Silent:
            checked = False

            def __init__(self):
                self.done = threading.Event()

            def wait(self):
                self.done.wait()
                return False

            def close(self):
                self.done.set()
        task = await self.run_box(Silent)
        self.clock.advance(59)
        self.assertEqual(await task, (False, False))

    async def test_terminal_ask_box_variants(self):
        async def with_box(title, text, box, timeout, sleep):
            return True, True
        dialog = types.SimpleNamespace(with_box=with_box)
        terminal = Terminal(clock=self.clock, sleep=self.clock.sleep, read_stdin=False, dialog=dialog)
        terminal.attention = lambda text: None
        self.assertEqual(await terminal.ask_box("q", dialog=("T", "M"), box="b"), (True, True))
        answers = iter([True])

        async def plain(title, text, timeout, sleep):
            return next(answers)
        terminal = Terminal(clock=self.clock, sleep=self.clock.sleep, read_stdin=False, dialog=plain)
        terminal.attention = lambda text: None
        self.assertEqual(await terminal.ask_box("q", dialog=("T", "M"), box="b"), (True, False))
        prompts = []
        console = Terminal(clock=self.clock, sleep=self.clock.sleep, read_stdin=True)
        replies = iter(["y", "n"])

        async def read(timeout):
            return next(replies)
        console.read = read
        console.ask = lambda question, timeout=60, dialog=None: _answer(prompts, question, read)
        self.assertEqual(await console.ask_box("go? ", box="tick?"), (True, False))
        self.assertEqual(len(prompts), 2)


async def _instant(delay):
    return None


async def _answer(prompts, question, read):
    prompts.append(question)
    return await read(0) == "y"


class StatusTests(unittest.TestCase):
    def test_stop_tools_callback_and_label(self):
        status, calls = Status(), []
        status.request_stop_tools()  # nothing registered: nothing happens
        status.stop_tools = lambda: calls.append(1)
        status.request_stop_tools()
        self.assertEqual(calls, [1])
        status.request_stop_checks()  # nothing registered: nothing happens
        status.stop_checks = lambda: calls.append("checks")
        status.request_stop_checks()
        self.assertEqual(calls, [1, "checks"])
        redrawn = []
        status.listeners.append(redrawn.append)
        status.changed()  # a menu item's availability changed, not the state
        self.assertEqual(redrawn, ["offline"])
        status.set("tools")
        self.assertIn("local tool", status.label)
        with contextlib.redirect_stdout(io.StringIO()):
            status.set("paired")
