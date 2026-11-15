"""Update coordination uses event fakes; prompts and possibly completed actions never grant implicitly."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper.client import Session
from partyline_helper import updates, update_recovery as recovery, update_prompts as prompts
from partyline_helper import update_preferences as preferences, update_cleanup as cleanup
from tests.screen_helper_fakes import FakeDesktop, FakeTerminal, FakeSocket


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "helper.json"
        self.patchers = [patch.object(module, "config_path", return_value=self.path) for module in
                         (preferences, recovery, updates.supervisor, cleanup,
                          __import__("partyline_helper.screen_access_audit", fromlist=["config_path"]))]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.session = Session(FakeSocket(), FakeDesktop(), FakeTerminal(), "Computer")
        self.session.window_access_audit = SimpleNamespace(append=Mock())
        self.session.send = AsyncMock()
        self.session.status.quit = Mock()
        self.session.updates.exit_process = Mock()
        self.session.windows.chrome.start = Mock()
        self.session.windows.start_events = AsyncMock()
        self.session.windows.outline_factory = Mock(return_value=SimpleNamespace(start=AsyncMock()))

    async def asyncTearDown(self):
        if timer := getattr(self.session.updates, "exit_timer", None):
            timer.cancel()
        await self.session.updates.close()
        for task in self.session.windows.tasks:
            task.cancel()
        await asyncio.gather(*self.session.windows.tasks, return_exceptions=True)

    def selected(self, hwnd=1):
        return {"hwnd": hwnd, "pid": 12, "process": "editor.exe", "title": "Document", "marker": "lifetime"}

    def data(self):
        return {"version": "1.7.0", "grants": [
            {"id": "kept", "selected": self.selected(), "target": {"line_id": "alpha", "line_name": "Alpha"},
             "standing_access": False},
            {"id": "stale", "selected": self.selected(2),
             "target": {"line_id": "alpha", "line_name": "Alpha"},
             "standing_access": False}]}

    async def test_restoration_rechecks_window_identity_and_floor_before_creating_workers(self):
        allowed = [{"id": row["id"], "hwnd": row["selected"]["hwnd"], "process": "editor.exe",
                    "conv_id": "alpha"} for row in self.data()["grants"]]
        checks = []
        class Access:
            def __init__(self, session, on_revoke):
                self.session, self.generation = session, 0
                self.gate = SimpleNamespace(grant=Mock())
            async def check(self, selected):
                checks.append(selected["hwnd"])
                return None if selected["hwnd"] == 1 else "window closed"
        restored = await recovery.restore(self.session, allowed, self.data(), Access)
        self.assertEqual(restored, ["kept"])
        self.assertEqual(checks, [1, 2])
        self.assertEqual(list(self.session.windows.grants), ["kept"])
        self.session.windows.grants.clear()
        data = self.data()
        data["grants"][0]["selected"]["process"] = "powershell.exe"
        data["grants"][1]["selected"].pop("marker")
        self.assertEqual(await recovery.restore(self.session, allowed, data, Access), [])

    async def test_snapshot_captures_requests_and_non_mouse_replay_is_an_information_notice(self):
        question = {"title": "Allow click?", "message": "Use the mouse?", "box": None, "labels": None}
        with patch.dict(prompts.PENDING, {42: question}):
            data = recovery.snapshot(self.session, "1.7.0")
        self.assertEqual(data["prompts"], [question])
        self.assertNotIn("token", recovery.path().read_text())
        confirm, tell = AsyncMock(return_value=(True, False)), Mock()
        await prompts.replay(data["prompts"], confirm, tell=tell)
        confirm.assert_not_awaited()
        self.assertIn("interrupted operation was cancelled", tell.call_args.args[1])
        self.assertIn(question["message"], tell.call_args.args[1])

    async def test_quiesce_invalidates_gates_cancels_prompt_and_uses_one_bounded_event_wait(self):
        async def pending():
            await asyncio.Event().wait()
        task = asyncio.create_task(pending())
        self.session.control.prompt = task
        self.session.window_task.actions.task = asyncio.get_running_loop().create_future()
        future = self.session.window_task.actions.task
        wait = AsyncMock(return_value=(set(), {future}))
        with patch.object(recovery.asyncio, "wait", wait):
            await recovery.quiesce(self.session)
        wait.assert_awaited_once()
        self.assertEqual(wait.call_args.kwargs["timeout"], 10)
        self.assertTrue(self.session.window.gate.revoked.is_set())
        self.assertTrue(future.cancelled())
        await asyncio.gather(task, return_exceptions=True)

    async def test_update_announces_persists_launches_and_exits_without_waiting_for_idle(self):
        updater = self.session.updates
        updater.enabled = True
        updater.fetch = Mock(return_value=self.root / "setup.exe")
        updater.launch = Mock(return_value="completion-event")
        async def send(kind, **fields):
            if kind == "helper_updating":
                self.assertTrue(updater.installing)
                updater.ack.set_result(True)
        self.session.send.side_effect = send
        with patch.object(recovery, "quiesce", AsyncMock()) as stop:
            await updater.attempt({"version": "1.7.0", "available": True})
        stop.assert_awaited_once()
        self.session.status.quit.assert_called_once()
        self.assertEqual(json.loads(recovery.path().read_text())["event"],
                         updater.launch.call_args.kwargs["name"])
        self.assertEqual(self.session.send.call_args.args[0], "helper_updating")

    async def test_not_published_and_failed_download_do_not_launch_or_retry(self):
        updater = self.session.updates
        updater.fetch = Mock(return_value=None)
        updater.launch = Mock()
        await updater.attempt({"version": "1.7.0"})
        updater.launch.assert_not_called()
        updater.fetch.side_effect = ValueError("bad checksum")
        await updater.attempt({"version": "1.7.0"})
        self.assertEqual(preferences.read()["failed_update"], "1.7.0")
        self.assertEqual(self.session.send.call_args.args[0], "helper_update_failed")
        updater.enabled = True
        with patch.object(updates.platform, "system", return_value="Windows"):
            updater.offer({"version": "1.7.0"})
        self.assertIsNone(updater.task)

    async def test_enable_setting_is_persisted_and_reported_without_granting_access(self):
        updater = self.session.updates
        await updater.setting(True)
        self.assertTrue(preferences.enabled())
        self.assertFalse(self.session.window_access_enabled)
        self.session.send.assert_awaited_with("auto_update_changed", enabled=True)

    async def test_new_helper_restores_then_completes_and_signals_supervisor(self):
        updater = self.session.updates
        recovery.snapshot(self.session, "1.7.0")
        data = json.loads(recovery.path().read_text())
        data["event"] = "completion"
        recovery.save_config(data, recovery.path())
        async def receive_ack(kind, **fields):
            if kind == "helper_update_restored":
                self.assertIsNotNone(updater.recovered)
        self.session.send.side_effect = receive_ack
        with patch.object(recovery, "restore", AsyncMock(return_value=["kept"])):
            await updater.restore([])
        self.session.send.assert_awaited_with("helper_update_restored", grants=["kept"], failed=False)
        with patch.object(updates.supervisor, "signal") as signal:
            updater.finished()
        signal.assert_called_once_with("completion")
        self.assertFalse(recovery.path().exists())
        await updater.prompt_task

    async def test_failed_installer_old_helper_restores_and_suppresses_failed_version(self):
        updater = self.session.updates
        recovery.snapshot(self.session, "1.7.0")
        result = self.root / "updates" / "result.json"
        result.parent.mkdir()
        result.write_text('{"failed":true}')
        with patch.object(recovery, "restore", AsyncMock(return_value=[])):
            await updater.restore([])
        self.session.send.assert_awaited_with("helper_update_restored", grants=[], failed=True)
        self.assertEqual(preferences.read()["failed_update"], "1.7.0")
        updater.finished()
        await updater.prompt_task
        self.assertFalse(result.exists())

    async def test_new_requests_are_paused_locally_before_any_worker_can_start(self):
        self.session.updates.installing = True
        for kind, reply in (("read_window_elements", "window_elements"),
                            ("window_click", "window_element_result"),
                            ("snapshot_window", "window_snapshot")):
            await self.session.dispatch({"type": kind, "request_id": "r", "grant_id": "g"})
            self.assertEqual(self.session.send.call_args.args[0], reply)
            self.assertEqual(self.session.send.call_args.kwargs["status"], "paused")
        self.assertIsNone(self.session.window_task.task)

    async def test_open_mouse_prompt_is_reasked_and_new_answer_applies_only_to_restored_grant(self):
        self.session.windows.grants = {"kept": {}}
        prompt = {"title": "Mouse click", "message": "Allow this window?", "scope": {
            "kind": "mouse", "grant": "kept"}}
        await prompts.replay([prompt], AsyncMock(return_value=(True, False)), self.session)
        self.assertTrue(self.session.windows.grants["kept"]["mouse_approved"])
        self.session.clock = lambda: 12
        await prompts.replay([prompt], AsyncMock(return_value=(False, False)), self.session)
        self.assertFalse(self.session.windows.grants["kept"]["mouse_approved"])
        self.assertEqual(self.session.windows.grants["kept"]["mouse_denied"], 12)
        self.session.windows.grants.clear()

    async def test_pending_prompt_is_durable_before_cancellation_and_removed_afterward(self):
        entered = asyncio.Event()
        @prompts.remember
        async def asking(*args):
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(asking("Question", "Request", 60, None, None))
        await entered.wait()
        self.assertEqual(next(iter(prompts.PENDING.values()))["message"], "Request")
        saved = recovery.snapshot(self.session, "1.7.0")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(prompts.PENDING, {})
        self.assertEqual(saved["prompts"][0]["title"], "Question")

    async def test_picker_children_are_closed_by_handle_before_the_saved_question_is_replayed(self):
        from partyline_helper import prompt_processes as children
        from subprocess import CalledProcessError, TimeoutExpired
        child = Mock()
        child.wait.return_value = 0
        self.assertEqual(children.run(["picker"], 60, popen=lambda *a, **k: child).returncode, 0)
        self.assertNotIn(child, children.CHILDREN)
        child.wait.return_value = 1
        with self.assertRaises(CalledProcessError):
            children.run(["picker"], 60, popen=lambda *a, **k: child)
        child.wait.side_effect = [TimeoutExpired("picker", 60), 0]
        with self.assertRaises(TimeoutExpired):
            children.run(["picker"], 60, popen=lambda *a, **k: child)
        child.kill.assert_called_once()
        children.remember(child)
        try:
            children.cancel_all()
            child.terminate.assert_called_once()
        finally:
            children.forget(child)

    async def test_launch_failure_removes_recovery_and_installer_and_restores_the_main_gate(self):
        updater = self.session.updates
        updater.enabled = True
        staged = self.root / "updates" / "staged" / "setup.exe"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"installer")
        updater.fetch = Mock(return_value=staged)
        updater.launch = Mock(side_effect=OSError("supervisor not ready"))
        self.session.window.grant = self.selected()
        self.session.window.gate.grant()
        self.session.window.check = AsyncMock(return_value=None)
        async def send(kind, **fields):
            if kind == "helper_updating":
                updater.ack.set_result(True)
        self.session.send.side_effect = send
        await updater.attempt({"version": "1.7.0"})
        self.assertFalse(recovery.path().exists())
        self.assertFalse(staged.exists())
        self.assertFalse(staged.parent.exists())
        self.assertFalse(self.session.window.gate.revoked.is_set())
        self.assertFalse(updates.Updates(self.session).recovering)
        self.session.status.quit.assert_not_called()
        self.assertEqual(self.session.send.call_args.args[0], "helper_update_failed")

    async def test_transient_download_failure_can_be_tried_on_a_new_release_event(self):
        updater = self.session.updates
        updater.enabled = True
        from urllib.error import HTTPError
        for error in (OSError("temporarily unavailable"),
                      HTTPError("https://example.test/asset", 503, "unavailable", {}, None)):
            updater.fetch = Mock(side_effect=[error, None])
            await updater.attempt({"version": "1.7.0"})
            self.assertNotIn("failed_update", preferences.read())
            with patch.object(updates.platform, "system", return_value="Windows"):
                updater.offer({"version": "1.7.0"})
                await updater.task
            self.assertEqual(updater.fetch.call_count, 2)

    async def test_failed_recovery_persist_does_not_launch_a_supervisor(self):
        updater = self.session.updates
        updater.enabled = True
        updater.fetch = Mock(return_value=self.root / "setup.exe")
        updater.launch = Mock()
        async def send(kind, **fields):
            if kind == "helper_updating":
                updater.ack.set_result(True)
        self.session.send.side_effect = send
        with patch.object(updates, "save_config", side_effect=OSError("cannot persist")):
            await updater.attempt({"version": "1.7.0"})
        updater.launch.assert_not_called()
        self.assertFalse(recovery.path().exists())

    async def test_cancelled_attempt_after_snapshot_does_not_leave_recovery_intent(self):
        updater = self.session.updates
        updater.enabled = True
        updater.fetch = Mock(return_value=self.root / "setup.exe")
        entered = asyncio.Event()
        async def quiet(session):
            entered.set()
            await asyncio.Event().wait()
        async def send(kind, **fields):
            if kind == "helper_updating":
                updater.ack.set_result(True)
        self.session.send.side_effect = send
        with patch.object(recovery, "quiesce", quiet):
            task = asyncio.create_task(updater.attempt({"version": "1.7.0"}))
            await entered.wait()
            self.assertTrue(recovery.path().exists())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(recovery.path().exists())
        self.assertFalse(updates.Updates(self.session).recovering)

    async def test_cancelled_download_discards_a_late_verified_installer(self):
        import threading
        updater = self.session.updates
        entered, cleaned = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        staged = self.root / "updates" / "late" / "setup.exe"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"installer")
        loop = asyncio.get_running_loop()
        def fetch(*args):
            loop.call_soon_threadsafe(entered.set)
            release.wait()
            return staged
        original = updates.remove_installer
        def remove(path):
            original(path)
            if path is not None:
                loop.call_soon_threadsafe(cleaned.set)
        updater.fetch = fetch
        with patch.object(updates, "remove_installer", remove):
            task = asyncio.create_task(updater.download({"version": "1.7.0"}))
            try:
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
            await cleaned.wait()
        self.assertFalse(staged.exists())

    async def test_interrupted_notice_uses_info_buttons_and_cancellable_lifecycle(self):
        from partyline_helper import consent_dialog
        with patch.object(consent_dialog, "default_backend", return_value=Mock()), \
                patch.object(consent_dialog, "_confirm", AsyncMock()) as showing:
            await prompts.replay([{"title": "Allow control?", "message": "Control request"}])
        self.assertEqual(showing.call_args.args[3].keywords["kind"], "info")
        self.assertIn("must be requested again", showing.call_args.args[1])
