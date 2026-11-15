"""Person-approved scope, immediate pause gates, and inherited action attribution."""
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper.screen_access_audit import ScreenAccessAudit
from partyline_helper.screen_access_toggle import pause_windows
from partyline_helper.status import Status
from partyline_helper.uia_task import WindowTask
from tests.window_grant_fixtures import WindowGrantFixture


class PauseOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stop_blocked_by_capture_still_revokes_and_closes_socket(self):
        from partyline_helper.client import Session
        from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal

        started, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def capture():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                # Capture/transport cleanup can defer cancellation until its resource releases.
                stopping.set()
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        pass

        socket = FakeSocket()
        session = Session(socket, FakeDesktop(), FakeTerminal(), "Desktop")
        session.accepted = True
        session.window.grant = {"hwnd": 1, "title": "Editor", "process": "editor.exe"}
        session.window.gate.grant()
        session.tools.audit = SimpleNamespace(append=Mock())
        session.windows.chrome.close = AsyncMock(side_effect=release.wait)
        session.worker = asyncio.create_task(capture())
        await started.wait()
        with patch("partyline_helper.screen_access_toggle.set_enabled", return_value=False):
            task = asyncio.create_task(pause_windows(session))
            try:
                await stopping.wait()
                self.assertIsNone(session.window.grant)
                self.assertTrue(session.window.gate.revoked.is_set())
                self.assertFalse(session.accepted)
                self.assertTrue(socket.closed_event.is_set())
                self.assertFalse(task.done())
            finally:
                release.set()
                await task

    async def test_blocked_stop_capture_and_chrome_do_not_delay_revocation_or_disconnect(self):
        disconnected, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        running = asyncio.Event()

        async def capture():
            running.set()
            await asyncio.Event().wait()

        worker = asyncio.create_task(capture())
        await running.wait()
        window = SimpleNamespace(revoke=Mock())
        windows = SimpleNamespace(revoke_all=Mock(), close=AsyncMock(side_effect=release.wait))
        control = SimpleNamespace(end=Mock())
        window_task = WindowTask(SimpleNamespace())
        window_task.task = asyncio.create_task(capture())
        window_task.read_task = asyncio.create_task(capture())
        cancellations = []

        async def blocked_stop(*_):
            cancellations.extend(bool(task.cancelling()) for task in
                                 (worker, window_task.task, window_task.read_task))
            started.set()
            await release.wait()

        async def disconnect(**_):
            disconnected.set()

        session = SimpleNamespace(status=Status(), window=window, windows=windows,
            control=control, worker=worker, window_task=window_task,
            stop=blocked_stop, tools=SimpleNamespace(end=AsyncMock(side_effect=release.wait)),
            send=AsyncMock(side_effect=release.wait), socket=SimpleNamespace(close=disconnect))
        with patch("partyline_helper.screen_access_toggle.set_enabled", return_value=False):
            task = asyncio.create_task(pause_windows(session))
            try:
                await started.wait()
                window.revoke.assert_called_once_with("access paused")
                windows.revoke_all.assert_called_once_with()
                control.end.assert_called_once_with("access paused")
                self.assertEqual([True, True, True], cancellations)
                self.assertTrue(disconnected.is_set())
                self.assertFalse(task.done())
                self.assertTrue(session.disconnect_requested)
                self.assertFalse(session.window_access_enabled)
            finally:
                release.set()
                await task
                await asyncio.gather(worker, return_exceptions=True)


class StandingOwnerBindingTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    def binding_url(self, device_id=None):
        return f"/api/screen/devices/{device_id or self.device['id']}/window-access-line"

    async def bind(self, line, user=None):
        return await self.client.put(self.binding_url(), json={"conv_id": line},
                                     headers=self.human(user or self.owner))

    async def discover(self, ident="a"):
        line = self.db.get_attachment(ident)["conv_id"]
        return await self.client.post(f"/api/conversations/{line}/screen-windows",
                                      headers=self.machine(ident))

    async def test_settings_pairing_and_existing_account_helpers_can_bind_then_discover(self):
        from partyline.auth_guard import Principal
        from partyline.screen_capabilities import for_attachment
        from partyline.screen_device_access import standing_devices
        from partyline.screen_snapshot import owner_devices

        # Settings pairing supplies no conv_id; an older account device has no mirror row.
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                code = self.hub.issue_pair_code(self.owner["id"])
                device_id, _, _, _ = self.hub.claim_pair_code(code, "Settings helper", "test")
                self.hub.devices.clear()
                self.device = {**self.device, "id": device_id, "conv_id": None}
                self.hub.devices[device_id] = self.device
                if legacy:
                    self.db._exec("DELETE FROM screen_device_window_access WHERE device_id=?", (device_id,))
                self.assertEqual(403, (await self.discover()).status_code)
                principal = Principal(kind="machine", name="a", attachment_id="a", conv_id="alpha")
                self.assertFalse(for_attachment(self.runtime, principal, "alpha", {})["window_access"])
                self.assertEqual(200, (await self.bind("alpha")).status_code)
                self.assertTrue(for_attachment(self.runtime, principal, "alpha", {})["window_access"])
                request = AsyncMock(return_value={"windows": []})
                with patch.object(self.hub.standing_windows, "request", request):
                    self.assertEqual(200, (await self.discover()).status_code)
                    self.assertEqual(403, (await self.discover("b")).status_code)
                self.db.create_conversation("child-" + device_id, "Child")
                child = "child-" + device_id
                self.db._exec("UPDATE conversations SET parent_id='alpha' WHERE id=?", (child,))
                self.assertEqual([self.device], standing_devices(self.hub, child))
                targets = {item["line_id"]: item for item in (await self.offer())["lines"]}
                self.assertTrue(targets["alpha"]["standing_access"])
                self.assertTrue(targets[child]["standing_access"])
                self.assertFalse(targets["beta"]["standing_access"])
                snapshot = next(d for d in owner_devices(self.hub, self.owner["id"]) if d["id"] == device_id)
                self.assertEqual("alpha", snapshot["window_access_line"])
                # Binding survives a helper reconnect; the hello only updates enabled.
                self.hub.devices[device_id] = dict(self.device)
                self.assertTrue(standing_devices(self.hub, "alpha"))

    async def test_machine_and_other_person_cannot_bind_a_paired_computer(self):
        response = await self.client.put(self.binding_url(), json={"conv_id": "beta"},
                                          headers=self.machine("a"))
        self.assertEqual(403, response.status_code)
        self.assertEqual(404, (await self.bind("beta", self.other_user)).status_code)
        self.assertEqual(404, (await self.bind("missing")).status_code)
        self.db._exec("UPDATE conversations SET archived_at=1 WHERE id='beta'")
        self.assertEqual(409, (await self.bind("beta")).status_code)
        self.db._exec("UPDATE screen_devices SET revoked_at=1 WHERE id=?", (self.device["id"],))
        self.assertEqual(404, (await self.bind("alpha")).status_code)

    async def test_unknown_or_mismatched_owner_never_inherits_standing_scope(self):
        for owner_id in (None, 987654, self.other_user["id"]):
            self.device["owner_id"] = owner_id
            self.assertEqual(403, (await self.discover()).status_code)
            offered = await self.offer()
            self.assertFalse(any(line["standing_access"] for line in offered["lines"]))

    async def test_clearing_binding_revokes_standing_grants_but_keeps_explicit_grants(self):
        await self.grant("a", standing_access=True)
        await self.grant("b", grant_id="explicit", hwnd=11)
        self.assertEqual(200, (await self.bind(None)).status_code)
        self.assertEqual(403, (await self.discover()).status_code)
        self.assertIsNone(self.db._exec("SELECT 1 FROM screen_line_window_grants WHERE id='g1'").fetchone())
        self.assertIsNotNone(self.db._exec(
            "SELECT 1 FROM screen_line_window_grants WHERE id='explicit'").fetchone())

    async def test_binding_change_removes_every_grant_before_blocked_notifications(self):
        await self.grant("a", standing_access=True)
        await self.grant("a", grant_id="second", hwnd=11, standing_access=True)
        entered, release = asyncio.Event(), asyncio.Event()

        async def announce(*_):
            entered.set()
            await release.wait()

        with patch("partyline.screen_window_grants.announce", side_effect=announce):
            task = asyncio.create_task(self.bind("beta"))
            try:
                await entered.wait()
                rows = self.db._exec("SELECT id FROM screen_line_window_grants WHERE standing_access=1")
                self.assertFalse(rows.fetchall())
                self.assertEqual(403, (await self.read("a")).status_code)
            finally:
                release.set()
                self.assertEqual(200, (await task).status_code)

    async def test_changing_the_device_owner_invalidates_existing_standing_grants(self):
        await self.grant("a", standing_access=True)
        self.device["owner_id"] = self.other_user["id"]
        self.assertEqual(403, (await self.read("a")).status_code)

    async def test_inherited_element_action_reaches_helper_audit_as_child(self):
        self.db.create_conversation("child", "Child")
        self.db._exec("UPDATE conversations SET parent_id='alpha' WHERE id='child'")
        self.db.add_attachment("child", "child", "child", "raw", ["shell"], "/tmp", "activation-child")
        await self.grant("a", standing_access=True)
        response = await self.act("child")
        self.assertEqual(200, response.status_code, response.text)
        message = next(m for m in reversed(self.sent) if m["type"] == "window_element_action")
        self.assertEqual("child", message["line"])
        self.assertEqual("child", message["line_id"])
        self.assertEqual("Child", message["line_name"])
        audit = ScreenAccessAudit(Path(self.tmp.name) / "audit.jsonl")
        parent = SimpleNamespace(window_access_audit=audit, status=Status(),
            windows=SimpleNamespace(grants={"g1": {"target": {"line_id": "alpha", "line_name": "Alpha"},
                                                  "process": "editor.exe", "title": "Editor"}}))
        session = SimpleNamespace(parent=parent, window_grant_id="g1", window=object(), send=AsyncMock(),
            chrome=SimpleNamespace(action=AsyncMock(return_value={"status": "completed"})))
        await WindowTask(session)._action(message)
        self.assertEqual("child", audit.recent()[0]["line"])
        rows = self.db._exec("SELECT entry FROM screen_control_audit WHERE conv_id='child'").fetchall()
        self.assertTrue(any("uia_action" in row["entry"] and "completed" in row["entry"] for row in rows))
