"""JavaScript dialogs wake blocked commands and require explicit, revocable input."""
import asyncio
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper.cdp_page_dialogs import PageDialog
from partyline_helper.uia_task import WindowTask
from tests.cdp_fakes import Fixture
from tests.screen_helper_fakes import checkpoint
from tests.test_cdp_recovery import Deadline
from tests.test_cdp_settle import Clock


class PageDialogs(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.clock = Clock()
        self.f.browser.timeout = lambda seconds: Deadline(self.clock, seconds)
        self.rows = await self.f.read()
        self.page = self.f.chrome.pages[self.f.access]["a"]
        self.page.quiet.wait = AsyncMock(return_value="quiet")
        self.worker = WindowTask(self.f.access.session)

    async def opening(self, kind="beforeunload"):
        self.f.socket.event("Page.javascriptDialogOpening", type=kind, message="Discard edits?",
                            url="https://example.test/form", defaultPrompt="Draft")
        await checkpoint()

    async def dialog(self, **extra):
        return await self.f.chrome.action(self.f.access,
            dict(action="dialog", element_id="page", **extra))

    async def test_reads_eval_actions_and_point_refuse_without_renderer_commands(self):
        await self.opening()
        before = len(self.f.socket.calls)
        self.assertEqual(self.page.page_dialog, dict(type="beforeunload", message="Discard edits?",
                         url="https://example.test/form", default_prompt="Draft"))
        result = await self.f.read()
        self.assertEqual(result["page_dialog"], self.page.page_dialog)
        self.assertIn('action="dialog"', result["error"])
        for message in (dict(type="window_eval", expression="1"),
                        dict(action="invoke", element_id=self.rows["elements"][1]["id"]),
                        dict(action="reload", element_id="page")):
            result = await self.f.chrome.action(self.f.access, message)
            self.assertEqual(result["status"], "failed")
            self.assertIn("page_dialog", result)
            self.assertNotIn("interrupted", result["error"])
        with self.assertRaises(PageDialog):
            await self.page.call("Input.dispatchMouseEvent", {})
        self.assertFalse(any(m.get("sessionId") == "a" for m in self.f.socket.calls[before:]))
        self.assertFalse(self.page.dispatched)

    async def test_cancel_closes_dialog_reads_resume_and_worker_audits(self):
        await self.opening()
        self.f.socket.hook = lambda m: self.f.socket.event("Page.javascriptDialogClosed") if (
            m["method"] == "Page.handleJavaScriptDialog") else None
        await self.worker._action(dict(action="dialog", element_id="page", accept=False,
                                       request_id="r", agent="agent"))
        reply = self.f.session.send.await_args.kwargs
        self.assertEqual(reply["status"], "completed")
        command = next(m for m in self.f.socket.calls if m["method"] == "Page.handleJavaScriptDialog")
        self.assertEqual(command["params"], {"accept": False})
        self.assertEqual(command["sessionId"], "a")
        self.assertIsNone(self.page.page_dialog)
        self.assertIn("elements", await self.f.read())
        self.f.session.tools.audit.append.assert_called()

    async def test_accept_beforeunload_and_prompt_text_are_exact(self):
        await self.opening()
        self.assertEqual((await self.dialog(accept=True))["status"], "completed")
        self.assertEqual(self.f.socket.calls[-1]["params"], {"accept": True})
        await self.opening("prompt")
        self.assertEqual((await self.dialog(accept=False, prompt_text="new text"))["status"], "completed")
        self.assertEqual(self.f.socket.calls[-1]["params"], {"accept": False, "promptText": "new text"})

    async def test_no_dialog_missing_accept_and_revoked_consent_send_no_command(self):
        self.assertIn("No JavaScript", (await self.dialog(accept=False))["error"])
        await self.opening("alert")
        self.assertIn("explicit accept", (await self.dialog())["error"])
        self.f.access.gate.revoked.set()
        self.assertEqual((await self.dialog(accept=True))["status"], "failed")
        self.assertFalse(any(m["method"] == "Page.handleJavaScriptDialog" for m in self.f.socket.calls))

    async def test_dialog_event_wakes_navigation_even_without_a_command_response(self):
        send = self.f.socket.send
        opened = asyncio.Event()
        async def modal(raw):
            message = json.loads(raw)
            if message["method"] == "Runtime.evaluate" and message["params"]["expression"] == "navigate()":
                self.f.socket.calls.append(message)
                self.f.socket.event("Page.javascriptDialogOpening", type="beforeunload", message="Leave?")
                opened.set()
                return  # Chrome withholds the result while the native dialog is open.
            await send(raw)
        self.f.socket.send = modal
        task = asyncio.create_task(self.f.chrome.action(self.f.access,
            dict(type="window_eval", expression="navigate()")))
        await opened.wait()
        await checkpoint()
        self.clock.advance(10)  # a regression finishes with its fake timeout, never a real wait
        result = await task
        self.assertEqual(result["page_dialog"]["type"], "beforeunload")
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("do not retry automatically", result["note"])
        self.assertNotIn("interrupted", result["error"])
        self.assertFalse(self.f.browser.pending)

    async def test_dialog_during_invoke_observation_preserves_in_flight_status_through_cleanup(self):
        response = self.f.socket.response
        def modal(message):
            if message["method"] == "Runtime.callFunctionOn":
                self.f.socket.event("Page.javascriptDialogOpening", type="confirm", message="Proceed?")
            return response(message)
        self.f.socket.response = modal
        result = await self.f.chrome.action(self.f.access,
            dict(action="invoke", element_id=self.rows["elements"][1]["id"]))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["page_dialog"]["type"], "confirm")
        self.assertIn("do not retry automatically", result["note"])
        self.assertFalse(self.page.dispatched)  # the CDP observation, rather than Input.*, was in flight
        self.assertEqual(self.f.socket.calls[-1]["method"], "Runtime.callFunctionOn")

    async def test_post_response_dialog_guard_marks_evaluation_as_in_flight(self):
        send = self.f.socket.send
        async def modal(raw):
            message = json.loads(raw)
            await send(raw)  # reply reaches the reader before the dialog event
            if message["method"] == "Runtime.evaluate" and message["params"]["expression"] == "navigate()":
                self.f.socket.event("Page.javascriptDialogOpening", type="beforeunload", message="Leave?")
        self.f.socket.send = modal
        result = await self.f.chrome.action(self.f.access, dict(type="window_eval", expression="navigate()"))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("do not retry automatically", result["note"])

    async def test_visibility_interrupted_on_first_candidate_selects_that_dialog_page(self):
        self.f.socket.titles["b"] = "Lab"
        self.f.chrome.selected[self.f.access] = "b"
        def modal(message):
            if (message["method"] == "Runtime.evaluate" and message.get("sessionId") == "a"
                    and "visibilityState" in message["params"]["expression"]):
                self.f.socket.event("Page.javascriptDialogOpening", type="confirm", message="Proceed?")
        self.f.socket.hook = modal
        page = await self.f.chrome.page(self.f.access)
        self.assertIs(page, self.page)
        self.assertEqual(self.f.chrome.selected[self.f.access], "a")
        self.assertEqual(page.page_dialog["type"], "confirm")
        self.assertEqual((await self.f.read())["page_dialog"]["type"], "confirm")

    async def test_visibility_dialog_guard_tolerates_page_loss_but_preserves_revocation(self):
        from partyline_helper.cdp_page_dialogs import visible
        from partyline_helper.cdp_transport import CDPError
        async def modal():
            self.page.page_state = "crashed"
            raise PageDialog(dict(type="confirm"))
        self.page.visible = modal
        self.assertFalse(await visible(self.page))
        self.page.page_state = "alive"
        self.f.access.gate.revoked.set()
        with self.assertRaisesRegex(CDPError, "revoked"):
            await visible(self.page)

    async def test_other_session_events_do_not_change_dialog_and_revocation_wins(self):
        self.f.socket.event("Page.javascriptDialogOpening", session="other", type="alert")
        await checkpoint()
        self.assertIsNone(self.page.page_dialog)
        await self.opening("confirm")
        self.f.socket.event("Page.javascriptDialogClosed", session="other")
        await checkpoint()
        self.assertIsNotNone(self.page.page_dialog)
        call = self.f.browser.call
        async def revoke(method, *args, **kwargs):
            if method == "Page.handleJavaScriptDialog":
                self.f.access.gate.revoked.set()
            return await call(method, *args, **kwargs)
        self.f.browser.call = revoke
        result = await self.dialog(accept=False)
        self.assertIn("revoked", result["error"])
        self.assertFalse(any(m["method"] == "Page.handleJavaScriptDialog" for m in self.f.socket.calls))

    async def test_point_route_reports_typed_dialog_before_any_input(self):
        from partyline_helper.window_click import PointClicks
        await self.opening()
        clicks = PointClicks(self.f.shares, clock=lambda: 100)
        entry = self.f.shares.grants["g"]
        with patch.object(clicks, "current", AsyncMock(return_value=[(10, 10)])), \
             patch.object(clicks, "record", Mock()):
            await clicks.handle(entry, dict(type="window_click", request_id="point", grant_id="g",
                                snapshot="s", x=10, y=10, screen=[10, 10], button="left", clicks=1))
        result = self.f.session.send.await_args.kwargs
        self.assertEqual(result["page_dialog"]["type"], "beforeunload")
        self.assertFalse(result["landing"]["input_sent"])

    async def test_opening_during_read_and_initialization_preserves_dialog(self):
        response = self.f.socket.response
        opening_on = "Accessibility.getFullAXTree"
        def dialog(m):
            if m["method"] == opening_on:
                self.f.socket.event("Page.javascriptDialogOpening", type="alert", message="Notice")
            return response(m)
        self.f.socket.response = dialog
        self.assertIn("page_dialog", await self.f.read())
        self.assertTrue(self.page.live)
        self.f.chrome.revoke(self.f.access)
        await checkpoint()
        opening_on = "Page.enable"
        self.assertIn("page_dialog", await self.f.read())
        page = self.f.chrome.pages[self.f.access]["a"]
        self.assertTrue(page.live)
        self.assertFalse(page.initialized)
        self.assertIn("page_dialog", await self.f.read())

    async def test_bounded_dialog_answer_and_prompt_audit_keeps_text_private(self):
        self.f.socket.event("Page.javascriptDialogOpening", type="prompt", message="💻" * 10000,
                            url="💻" * 10000, defaultPrompt="💻" * 10000)
        await checkpoint()
        self.assertEqual(len(self.page.page_dialog["message"]), 10000)
        result = await self.f.read()
        self.assertLess(len(json.dumps(result, ensure_ascii=False).encode()), 4096)
        await self.dialog(accept=False, prompt_text="private replacement")
        audit = self.f.session.tools.audit.append.call_args.args[-1]
        self.assertNotIn("private replacement", audit)
        self.assertEqual(json.loads(audit)["input_length"], len("private replacement"))
        self.assertIs(json.loads(audit)["accept"], False)


class ExtensionDialogs(IsolatedAsyncioTestCase):
    async def test_native_framed_transport_reports_handles_and_resumes_reads(self):
        from tests.extension_fakes import fixture
        f, peer = fixture()
        self.addAsyncCleanup(f.close)
        await f.read()
        page = f.chrome.pages[f.access][f.chrome.selected[f.access]]
        peer.feed(dict(method="Page.javascriptDialogOpening", sessionId=page.session,
                       params=dict(type="beforeunload", message="Leave?", url="https://example.test/form")))
        await f.browser.call("Browser.getVersion")  # native protocol fence
        before = len(peer.calls)
        self.assertEqual((await f.read())["page_dialog"]["type"], "beforeunload")
        self.assertFalse(any(m.get("sessionId") == page.session for m in peer.calls[before:]))
        result = await f.chrome.action(f.access, dict(action="dialog", element_id="page", accept=False))
        self.assertEqual(result["status"], "completed")
        command = next(m for m in peer.calls if m["method"] == "Page.handleJavaScriptDialog")
        self.assertEqual(command["sessionId"], page.session)
        self.assertEqual(command["params"], {"accept": False})
        peer.feed(dict(method="Page.javascriptDialogClosed", sessionId=page.session,
                       params={"result": False}))
        await f.browser.call("Browser.getVersion")
        self.assertIn("elements", await f.read())
        peer.feed(dict(method="Page.javascriptDialogOpening", sessionId=page.session,
                       params=dict(type="confirm", message="Proceed?")))
        await f.browser.call("Browser.getVersion")
        f.access.gate.revoked.set()
        before = len(peer.calls)
        await f.chrome.action(f.access, dict(action="dialog", element_id="page", accept=True))
        self.assertFalse(any(m["method"] == "Page.handleJavaScriptDialog" for m in peer.calls[before:]))
