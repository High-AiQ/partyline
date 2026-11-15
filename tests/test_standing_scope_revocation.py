"""Person-side scope changes revoke the real helper's standing grants and indicators."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline_helper.client import Session
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_task import WindowTask
from partyline_helper.window_shares import WindowSession
from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal
from tests.test_window_shares_helper import FakeOutline
from tests.window_grant_fixtures import WindowGrantFixture


class StandingScopeRevocationTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def check_binding_change(self, line):
        await self.grant("a", standing_access=True)
        await self.grant("a", grant_id="second", hwnd=11, standing_access=True)
        await self.grant("b", title="Explicit", grant_id="explicit", hwnd=12)
        helper = Session(FakeSocket(), FakeDesktop(), FakeTerminal(), "Computer")
        helper.tools.audit = SimpleNamespace(append=Mock())
        entries = {}
        for ident, hwnd, target in (("g1", 10, "Alpha"), ("second", 11, "Alpha"),
                                    ("explicit", 12, "Beta")):
            session = WindowSession(helper, ident, helper.windows.changed)
            access = WindowAccess(session)
            access.grant = {"hwnd": hwnd, "pid": 42, "title": ident, "process": "editor.exe"}
            access.gate.grant()
            session.window = access
            entries[ident] = {"access": access, "worker": WindowTask(session), "title": ident,
                              "process": "editor.exe", "standing_access": ident != "explicit",
                              "target": {"line_id": target.lower(), "line_name": target},
                              "outline": FakeOutline(hwnd), "events": SimpleNamespace(close=Mock())}
        helper.windows.grants.update(entries)
        helper.windows.changed()
        self.assertIn("Alpha", helper.status.window_title)

        async def receive(message):
            await self.receive(message)
            if message["type"] == "revoke_window":
                await helper.dispatch(message)

        self.device["socket"].send_json = receive
        self.sent.clear()
        try:
            response = await self.client.put(
                f"/api/screen/devices/{self.device['id']}/window-access-line",
                json={"conv_id": line}, headers=self.human(self.owner))
            self.assertEqual(200, response.status_code, response.text)
            messages = [m["grant_id"] for m in self.sent if m["type"] == "revoke_window"]
            self.assertCountEqual(["g1", "second"], messages)
            await asyncio.gather(*helper.windows.tasks)
            self.assertEqual({"explicit"}, set(helper.windows.grants))
            self.assertEqual({"explicit"}, set(helper.status.window_grants))
            self.assertNotIn("Alpha", helper.status.window_title)
            for ident in ("g1", "second"):
                self.assertTrue(entries[ident]["access"].gate.revoked.is_set())
                self.assertIsNone(entries[ident]["access"].grant)
                self.assertTrue(entries[ident]["outline"].closed)
                entries[ident]["events"].close.assert_called_once()
            self.assertFalse(entries["explicit"]["outline"].closed)
            self.assertFalse(entries["explicit"]["access"].gate.revoked.is_set())
            entries["explicit"]["events"].close.assert_not_called()
        finally:
            await helper.windows.close()

    async def test_clearing_binding_notifies_helper_and_removes_local_standing_grants(self):
        await self.check_binding_change(None)

    async def test_changing_binding_notifies_helper_and_removes_local_standing_grants(self):
        await self.check_binding_change("beta")

    async def test_helper_toggle_off_mirror_stays_quiet(self):
        from partyline.screen_standing import update_mirror

        await self.grant("a", standing_access=True)
        self.sent.clear()
        await update_mirror(self.hub, self.device, {"type": "window_access_changed", "enabled": False})
        self.assertFalse(any(message["type"] == "revoke_window" for message in self.sent))
        self.assertIsNone(self.db._exec("SELECT 1 FROM screen_line_window_grants WHERE id='g1'").fetchone())
