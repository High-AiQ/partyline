"""Helper-side local tools: per-session consent, kill switches, lease, audit and fail-closed behaviour."""
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from partyline_helper import tools
from partyline_helper.client import Session
from partyline_helper.tools_addon import AddonError
from partyline_helper.tools_audit import ToolAudit
from tests.screen_helper_fakes import (
    FakeDesktop, FakeInputs, FakeSocket, FakeTerminal, ManualTime, checkpoint,
)

ASK = dict(type="tools_request", session_id="s1", tool="blender", requested_by="agent-x",
           line_name="line", checker=False, scope_only=False)


async def until(condition, limit=10_000):
    for _ in range(limit):
        if condition():
            return
        await checkpoint()
    raise AssertionError("condition never became true")


class FakeAddon:
    def __init__(self):
        self.opened, self.closed, self.cancelled, self.calls = [], [], [], []
        self.renewals = []  # scripted renew answers: None alive, a string ended, AddonError unreachable
        self.info_error = self.open_error = None
        self.release = None  # a Future a call waits on
        self.reply = {"result": {"ok": True, "stdout": "hi\n", "result": None}}

    async def info(self):
        if self.info_error:
            raise self.info_error
        return {"ok": True, "file": "scene.blend", "blender": "5.2.2"}

    async def open_session(self, session_id, agent, checker):
        if self.open_error:
            raise self.open_error
        self.opened.append((session_id, agent, checker))
        return {"ok": True, "backup": "scene.agent-backup.blend"}

    async def renew(self, session_id):
        answer = self.renewals.pop(0) if self.renewals else None
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close_session(self, session_id):
        self.closed.append(session_id)

    async def call(self, session_id, call_id, op, args, timeout):
        self.calls.append((session_id, call_id, op, args, timeout))
        if self.release:
            await self.release
        return self.reply

    async def cancel(self, session_id, call_id):
        self.cancelled.append(call_id)
        if self.release and not self.release.done():
            self.release.set_result(None)


class ToolsHelperTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desktop, self.terminal, self.socket = FakeDesktop(), FakeTerminal(), FakeSocket()
        self.clock = ManualTime()
        self.inputs = FakeInputs(self.desktop)
        self.session = Session(self.socket, self.desktop, self.terminal, "desk", clock=self.clock,
                               sleep=self.clock.sleep, inputs=self.inputs)
        self.addon = FakeAddon()
        self.tools = self.session.tools
        self.tools.addon_for = lambda spec: self.addon
        self.audit_path = Path(self.tmp.name) / "audit.jsonl"
        self.tools.audit = ToolAudit(self.audit_path, clock=self.clock)
        self.terminal.box_answer = (True, False)
        self.out = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.out)
        self.redirect.__enter__()

    async def asyncTearDown(self):
        await self.tools.end("test over")
        self.redirect.__exit__(None, None, None)
        self.tmp.cleanup()

    async def grant(self, **extra):
        await self.session.dispatch(dict(ASK, **extra))
        return await self.socket.next("tools_granted")

    def audit_rows(self):
        return [json.loads(line) for line in self.audit_path.read_text().splitlines()]

    async def test_grant_asks_with_unticked_box_and_opens_the_session(self):
        granted = await self.grant()
        self.assertEqual((granted["checker"], granted["info"]["file"]), (False, "scene.blend"))
        self.assertEqual(self.addon.opened, [("s1", "agent-x", False)])
        title, message = self.terminal.dialogs[0]
        self.assertIn("allow agent-x to run Python in Blender", title)
        self.assertIn("A backup copy of the open file", message)
        self.assertIn("Each session asks again", message)
        self.assertEqual(self.terminal.boxes, [None])  # no checkbox unless the agent asked for it
        self.assertTrue(self.session.status.tools_active)
        self.assertIn("LOCAL TOOLS ACTIVE", self.out.getvalue())

    async def test_checker_box_only_when_asked_and_only_with_a_yes(self):
        self.terminal.box_answer = (True, True)
        granted = await self.grant(checker=True)
        self.assertTrue(granted["checker"])
        self.assertIn("OpenAI", self.terminal.boxes[0])
        self.assertEqual(self.addon.opened[0][2], True)
        await self.tools.drop("done", local=False, tell=False)
        self.terminal.box_answer = (True, True)  # a ticked box without the agent asking is ignored
        granted = await self.grant(session_id="s2", checker=False)
        self.assertFalse(granted["checker"])

    async def test_decline_and_silence_grant_nothing(self):
        self.terminal.box_answer = (False, False)  # the dialog returns this for No and for a timeout alike
        await self.session.dispatch(ASK)
        revoked = await self.socket.next("tools_revoked")
        self.assertIn("declined or timed out", revoked["reason"])
        self.assertEqual(self.addon.opened, [])
        self.assertIsNone(self.tools.grant)
        self.assertFalse(self.session.status.tools_active)

    async def test_nothing_is_granted_without_a_request_even_if_the_server_calls(self):
        await self.session.dispatch(dict(type="tool_call", session_id="s1", call_id="c1", op="exec",
                                         args={"code": "1"}, timeout=5))
        refused = await self.socket.next("tool_result")
        self.assertEqual((refused["ok"], refused["error"]), (False, "no active local tools session"))
        self.assertEqual(self.addon.calls, [])

    async def test_missing_addon_and_unknown_tool_are_refused_without_a_dialog(self):
        self.addon.info_error = AddonError("no Blender add-on found")
        await self.session.dispatch(ASK)
        self.assertIn("no Blender", (await self.socket.next("tools_revoked"))["reason"])
        await self.session.dispatch(dict(ASK, tool="paint"))
        self.assertIn("no adapter", (await self.socket.next("tools_revoked"))["reason"])
        self.assertEqual(self.terminal.dialogs, [])

    async def test_kill_switch_listener_failure_refuses_the_session(self):
        self.session.control.make_inputs = FakeInputs(self.desktop, "init")
        await self.session.dispatch(ASK)
        self.assertIn("kill switch unavailable", (await self.socket.next("tools_revoked"))["reason"])
        self.assertEqual(self.addon.opened, [])
        self.addon.open_error = AddonError("session already active")
        self.session.control.make_inputs = self.inputs
        await self.session.dispatch(dict(ASK, session_id="s2"))
        self.assertIn("already active", (await self.socket.next("tools_revoked"))["reason"])
        self.assertTrue(self.inputs.stopped)

    async def test_exec_is_audited_before_it_runs_and_the_result_returned(self):
        await self.grant()
        code = "import bpy\nprint(len(bpy.data.objects))"

        async def during_call():
            self.assertEqual([row["kind"] for row in self.audit_rows()], ["event", "call"])
            return self.addon.reply
        self.addon.call = lambda *args: during_call()
        await self.session.dispatch(dict(type="tool_call", session_id="s1", call_id="c1", op="exec",
                                         args={"code": code}, timeout=5))
        result = await self.socket.next("tool_result")
        self.assertEqual((result["ok"], result["result"]["stdout"]), (True, "hi\n"))
        rows = self.audit_rows()
        self.assertEqual([row["kind"] for row in rows], ["event", "call", "result"])
        self.assertEqual(rows[1]["code"], code)
        self.assertEqual(rows[1]["agent"], "agent-x")
        for earlier, later in zip(rows, rows[1:], strict=False):
            self.assertEqual(later["prev"], earlier["hash"])

    async def test_bad_calls_are_refused(self):
        await self.grant()
        for call, error in (
                (dict(session_id="other", op="exec", args={}), "no active"),
                (dict(session_id="s1", op="format_disk", args={}), "unsupported operation"),
                (dict(session_id="s1", op="exec", args="x"), "arguments must be an object")):
            await self.session.dispatch(dict(type="tool_call", call_id="c", timeout="soon", **call))
            self.assertIn(error, (await self.socket.next("tool_result"))["error"])
        self.assertEqual(self.addon.calls, [])

    async def test_unwritable_audit_log_fails_closed(self):
        await self.grant()
        self.tools.audit = ToolAudit(Path(self.tmp.name))  # a directory: appending raises OSError
        await self.session.dispatch(dict(type="tool_call", session_id="s1", call_id="c1", op="exec",
                                         args={"code": "1"}, timeout=5))
        self.assertIn("audit log cannot be written", (await self.socket.next("tool_result"))["error"])
        self.assertEqual(self.addon.calls, [])

    async def test_oversized_results_and_addon_errors_come_back_as_failures(self):
        await self.grant()
        self.addon.reply = {"result": {"ok": True, "stdout": "x" * (tools.MAX_RESULT + 1)}}
        for reply, text in ((self.addon.reply, "too large"), ({"error": "busy", "busy": True}, "busy")):
            self.addon.reply = reply
            await self.session.dispatch(dict(type="tool_call", session_id="s1", call_id="c", op="exec",
                                             args={"code": "1"}, timeout=5))
            failed = await self.socket.next("tool_result")
            self.assertFalse(failed["ok"])
            self.assertIn(text, failed["error"])

    async def test_runaway_call_is_cancelled_by_the_server(self):
        await self.grant()
        self.addon.release = asyncio.get_running_loop().create_future()
        await self.session.dispatch(dict(type="tool_call", session_id="s1", call_id="c1", op="exec",
                                         args={"code": "while True: pass"}, timeout=1))
        await until(lambda: self.addon.calls)
        await self.session.dispatch(dict(type="tool_cancel", call_id="c1"))
        await until(lambda: not self.tools.calls)
        self.assertEqual(self.addon.cancelled, ["c1"])
        self.assertEqual(self.audit_rows()[-1]["entry"], "cancelled")

    async def test_server_revoke_ends_the_session_and_closes_the_addon(self):
        await self.grant()
        await self.session.dispatch(dict(type="tools_revoked", session_id="s1", reason="by person"))
        self.assertEqual(self.addon.closed, ["s1"])
        self.assertIsNone(self.tools.grant)
        self.assertFalse(self.session.status.tools_active)
        self.assertEqual(self.socket.messages["tools_revoked"].qsize(), 0)  # the server already knows
        self.assertIn("revoked from Partyline (by person)", self.audit_rows()[-1]["entry"])

    async def test_hotkey_tray_and_blender_end_kill_without_the_server_then_cool_down(self):
        for index, trigger in enumerate(("hotkey", "tray", "app")):
            session_id = f"k{index}"
            await self.grant(session_id=session_id)
            if trigger == "hotkey":
                for name in ("ctrl", "alt", "esc"):
                    self.inputs.on_key(name, False, True)
            elif trigger == "tray":
                self.session.status.request_stop_tools()
            else:
                self.addon.renewals = ["app"]
                self.clock.advance(tools.RENEW)
            revoked = await self.socket.next("tools_revoked")
            self.assertEqual(revoked["session_id"], session_id)
            self.assertIsNone(self.tools.grant)
            self.assertIn(session_id, self.addon.closed)
            self.inputs.on_key("esc", False, False)
            await self.session.dispatch(dict(ASK, session_id="again"))  # the agent asks right back
            self.assertIn("may ask again in 10 min", (await self.socket.next("tools_revoked"))["reason"])
            self.clock.advance(tools.COOLDOWN)
            self.assertEqual(self.terminal.dialogs[-1][0].split()[0], "Partyline:")
        self.assertEqual(len(self.addon.opened), 3)

    async def test_lease_lapse_unreachable_addon_and_idle_expiry_end_it_without_cooldown(self):
        await self.grant()
        self.addon.renewals = ["lease"]
        self.clock.advance(tools.RENEW)
        self.assertIn("lease lapsed", (await self.socket.next("tools_revoked"))["reason"])
        await self.grant(session_id="s2")  # no cooldown: not a person's kill
        self.addon.renewals = [AddonError("down")] * tools.LOST
        for _ in range(tools.LOST):
            self.clock.advance(tools.RENEW)
            await checkpoint()
        self.assertIn("unreachable", (await self.socket.next("tools_revoked"))["reason"])
        await self.grant(session_id="s3")
        self.clock.advance(tools.IDLE)
        self.assertIn("idle for 15 minutes", (await self.socket.next("tools_revoked"))["reason"])
        self.assertIsNone(self.tools.grant)

    async def test_a_second_request_while_prompting_or_active_is_refused(self):
        self.terminal.box_answer = asyncio.get_running_loop().create_future()
        await self.session.dispatch(ASK)
        await until(lambda: self.terminal.asks.qsize())
        await self.session.dispatch(dict(ASK, session_id="s2"))
        self.assertEqual((await self.socket.next("tools_revoked"))["reason"], "prompt pending")
        await self.session.dispatch(dict(type="tools_revoked", session_id="s1", reason="withdrawn"))
        self.assertIn("withdrawn", self.out.getvalue())
        self.terminal.box_answer = (True, False)
        await self.grant(session_id="s3")
        await self.session.dispatch(dict(ASK, session_id="s4"))
        self.assertIn("another session", (await self.socket.next("tools_revoked"))["reason"])

    async def test_render_checks_need_a_fresh_yes_on_a_live_session(self):
        await self.grant()
        self.terminal.asks.get_nowait()
        self.terminal.control_answer = True
        await self.session.dispatch(dict(ASK, checker=True, scope_only=True))
        self.assertTrue((await self.socket.next("tools_granted"))["checker"])
        self.assertIn("render checks", self.terminal.dialogs[-1][0])
        self.terminal.control_answer = False
        await self.session.dispatch(dict(ASK, checker=True, scope_only=True))
        declined = await self.socket.next("tools_revoked")
        self.assertIn("declined", declined["reason"])
        self.assertTrue(declined["scope_only"])  # the server must keep the session
        self.assertIsNotNone(self.tools.grant)  # declining the extra scope leaves the session
        await self.tools.drop("done", local=False, tell=False)
        await self.session.dispatch(dict(ASK, scope_only=True))  # nothing live to add it to
        self.assertIn("no live session", (await self.socket.next("tools_revoked"))["reason"])

    async def test_every_kill_during_a_render_check_question_ends_the_session_and_the_question(self):
        for index, trigger in enumerate(("hotkey", "tray", "app")):
            session_id = f"e{index}"
            await self.grant(session_id=session_id)
            self.terminal.control_answer = asyncio.get_running_loop().create_future()
            await self.session.dispatch(dict(ASK, session_id=session_id, checker=True, scope_only=True))
            await until(lambda: self.tools.prompting)
            if trigger == "hotkey":
                for name in ("ctrl", "alt", "esc"):
                    self.inputs.on_key(name, False, True)
                self.inputs.on_key("esc", False, False)
            elif trigger == "tray":
                self.session.status.request_stop_tools()
            else:
                self.addon.renewals = ["app"]
                self.clock.advance(tools.RENEW)
            revoked = await self.socket.next("tools_revoked")
            self.assertEqual(revoked["session_id"], session_id)
            self.assertNotIn("scope_only", revoked)  # the whole session, not just the extra scope
            self.assertIsNone(self.tools.grant)
            self.assertFalse(self.tools.prompting)  # the dialog was withdrawn with the session
            self.clock.advance(tools.COOLDOWN)  # after the cool-down a new session can be asked for
            self.terminal.box_answer = (True, False)
            self.assertEqual((await self.grant(session_id=f"again{index}"))["session_id"], f"again{index}")
            await self.tools.drop("next round", local=False, tell=False)

    async def test_ending_the_connection_ends_the_session(self):
        await self.grant()
        await self.tools.end("disconnected")
        self.assertEqual(self.addon.closed, ["s1"])
        self.assertIsNone(self.tools.grant)
