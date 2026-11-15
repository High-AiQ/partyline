"""Standing screen permission is helper-owned, server-mirrored and fail closed."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper.screen_access import enabled, set_enabled
from partyline_helper.screen_access_audit import ScreenAccessAudit
from partyline_helper.status import Status
from partyline_helper.uia_window_list import discover_windows, standing_windows
from tests.window_grant_fixtures import WindowGrantFixture


class HelperWindowPermissionTests(unittest.TestCase):
    def test_persisted_permission_defaults_off_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "helper.json"
            self.assertFalse(enabled(path))
            path.write_text('{"server":"https://example.test","token":"old"}', encoding="utf-8")
            self.assertTrue(set_enabled(True, path))
            self.assertTrue(enabled(path))
            self.assertEqual("old", __import__("json").loads(path.read_text())["token"])
            self.assertFalse(set_enabled(False, path))
            self.assertFalse(enabled(path))

    def test_window_provider_filters_the_hard_floor(self):
        rows = [
            {"hwnd": 1, "process": "browser.exe", "title": "Catalog", "state": "active"},
            {"hwnd": 2, "process": "powershell.exe", "title": "shell", "state": "visible"},
            {"hwnd": 3, "process": "1Password.exe", "title": "vault", "state": "visible"},
            {"hwnd": 4, "process": "PartylineHelper.exe", "title": "helper", "state": "visible"},
            {"hwnd": 5, "process": "wezterm-gui.exe", "title": "terminal", "state": "visible"},
            {"hwnd": 6, "process": "alacritty.exe", "title": "terminal", "state": "visible"},
            {"hwnd": 7, "process": "Hyper.exe", "title": "terminal", "state": "visible"},
            {"hwnd": 8, "process": "Tabby.exe", "title": "terminal", "state": "visible"},
        ]
        with patch("partyline_helper.uia_window_list.window_providers",
                   return_value=(lambda: rows, lambda: ())):
            self.assertEqual([{**rows[0], "id": "1"}], standing_windows())

    def test_browser_provider_exposes_inactive_tab_url_and_stable_window_id(self):
        rows = [{"hwnd": 12, "pid": 9, "process": "chrome.exe", "title": "Active tab",
                 "state": "active"}]
        tab = {"hwnd": 12, "title": "Catalog editor", "url": "https://example.test/edit"}
        with patch("partyline_helper.uia_window_list.windows", return_value=rows), \
                patch("partyline_helper.uia_window_list.browser_tabs", return_value=(tab,)):
            found = standing_windows(access=object())
        self.assertEqual("https://example.test/edit", found[1]["url"])
        self.assertEqual("12:https://example.test/edit", found[1]["id"])
        self.assertEqual("active", found[1]["state"])

    def test_additional_windows_terminal_hosts_and_their_tabs_are_never_discovered(self):
        terminals = ("ConEmu.exe", "ConEmu64.exe", "Cmder.exe", "MobaXterm.exe", "Termius.exe", "Warp.exe")
        rows = [{"hwnd": index, "process": process, "title": "Terminal", "state": "visible"}
                for index, process in enumerate(terminals, 1)]
        safe = {"hwnd": 20, "process": "editor.exe", "title": "Document", "state": "visible"}
        tabs = [{"hwnd": row["hwnd"], "title": "Terminal tab", "url": "https://example.test"}
                for row in rows]
        with patch("partyline_helper.uia_window_list.window_providers",
                   return_value=(lambda: [*rows, safe], lambda: tabs)):
            self.assertEqual([{**safe, "id": "20"}], standing_windows())

    def test_discovery_scopes_chrome_tabs_to_an_enumerated_safe_window(self):
        row = {"hwnd": 12, "pid": 9, "process": "chrome.exe", "title": "Catalog Dashboard",
               "state": "active", "id": "12"}
        chrome = SimpleNamespace(
            browser=SimpleNamespace(state="connected", socket=object()),
            tabs=AsyncMock(return_value=[{"hwnd": 12, "title": "Listing Content Manager",
                                          "url": "https://shop.us/manage-listing-content",
                                          "target_id": "target-1",
                                          "active": False}]),
            revoke=Mock(),
        )
        session = SimpleNamespace(window_access_enabled=True, windows=SimpleNamespace(chrome=chrome))

        class Access:
            def __init__(self, _session):
                self.gate = SimpleNamespace(grant=Mock(), invalidate=Mock())
                self.grant = None
            async def check(self, grant):
                return None if self.grant is grant else "window closed"

        with patch("partyline_helper.uia_window_list.standing_windows", return_value=[row]), \
                patch("partyline_helper.uia_window_identity.mark",
                      side_effect=("window-lifetime-1", "window-lifetime-2")), \
                patch("partyline_helper.uia_access.WindowAccess", Access):
            found = asyncio.run(discover_windows(session))
        self.assertEqual("12:target-1", found[1]["id"])
        self.assertEqual("Listing Content Manager", found[1]["title"])
        self.assertEqual("window-lifetime-2", found[1]["marker"])
        self.assertEqual("target-1", found[1].get("target_id"))
        self.assertFalse(found[1]["tab_active"])
        chrome.tabs.assert_awaited_once()
        chrome.revoke.assert_called_once()

    def test_secure_desktop_stops_before_chrome_tab_enumeration(self):
        chrome = SimpleNamespace(browser=SimpleNamespace(state="connected", socket=object()),
                                 tabs=AsyncMock())
        session = SimpleNamespace(window_access_enabled=True, windows=SimpleNamespace(chrome=chrome))
        with patch("partyline_helper.uia_window_list.standing_windows", return_value=None):
            self.assertIsNone(asyncio.run(discover_windows(session)))
        chrome.tabs.assert_not_awaited()

    def test_local_audit_is_metadata_only_and_recent_is_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = ScreenAccessAudit(Path(directory) / "audit.jsonl", clock=lambda: 12.0)
            audit.append("line-a", "agent", "uia_read", "browser.exe", "Catalog", "read")
            self.assertEqual("Catalog", audit.recent()[0]["title"])
            raw = audit.path.read_text(encoding="utf-8")
            self.assertNotIn("page body", raw)
            self.assertIn('"line":"line-a"', raw)

    def test_inherited_call_audit_uses_caller_line_for_log_and_active_status(self):
        from partyline_helper.screen_access_audit import audit_window, begin_window_call, end_window_call
        with tempfile.TemporaryDirectory() as directory:
            audit = ScreenAccessAudit(Path(directory) / "audit.jsonl", clock=lambda: 12.0)
            status = Status()
            access = SimpleNamespace(window_access_audit=audit, window_grant_id="grant-1")
            parent = SimpleNamespace(window_access_audit=audit, status=status,
                                     windows=SimpleNamespace(grants={"grant-1": {
                                         "target": {"line_id": "root", "line_name": "Root"},
                                         "process": "chrome.exe", "title": "Catalog"}}))
            access.parent = parent
            call = begin_window_call(access, "worker", "Subline")
            audit_window(access, "uia_read", "worker", "read", "subline-id")
            self.assertEqual(("Subline", "worker"), status.window_access_active)
            end_window_call(call)
            self.assertEqual("subline-id", audit.recent()[0]["line"])


class ServerWindowPermissionTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def test_toggle_mirror_denies_previously_granted_window_calls(self):
        await self.grant("a", standing_access=True)
        self.device["window_access_enabled"] = False
        self.db._exec("UPDATE screen_device_window_access SET enabled=0 WHERE device_id=?",
                      (self.device["id"],))
        response = await self.read("a")
        self.assertEqual(403, response.status_code)
        self.assertIn("no window is shared", response.text)

    async def test_helper_can_revoke_grants_after_toggle_turns_off(self):
        await self.grant("a")
        self.device["window_access_enabled"] = False
        await self.hub.window_grants.from_helper(
            self.device, {"type": "window_revoked", "grant_id": "g1"})
        row = self.db._exec("SELECT 1 FROM screen_line_window_grants WHERE id='g1'").fetchone()
        self.assertIsNone(row)

    async def test_explicit_line_grants_keep_their_consent_when_the_standing_toggle_is_off(self):
        await self.grant("a")
        self.device["window_access_enabled"] = False
        self.db._exec("UPDATE screen_device_window_access SET enabled=0 WHERE device_id=?",
                      (self.device["id"],))
        response = await self.read("a")
        self.assertEqual(200, response.status_code, response.text)

    async def test_turning_off_revokes_only_standing_grants(self):
        await self.grant("a", standing_access=True)
        await self.grant("b", grant_id="g2", hwnd=11)
        await self.hub.window_grants.revoke_standing(self.device["id"])
        self.assertIsNone(self.db._exec(
            "SELECT 1 FROM screen_line_window_grants WHERE id='g1'").fetchone())
        self.assertIsNotNone(self.db._exec(
            "SELECT 1 FROM screen_line_window_grants WHERE id='g2'").fetchone())

    async def test_discovery_is_owned_line_only_and_server_mirrors_on(self):
        request = AsyncMock(return_value={"windows": [{"hwnd": 42, "process": "browser.exe",
                                                         "title": "Catalog", "state": "active", "pid": 8}]})
        with patch.object(self.hub.standing_windows, "request", request):
            response = await self.client.post("/api/conversations/alpha/screen-windows",
                                              headers=self.machine("a"))
            self.assertEqual(200, response.status_code)
            self.assertEqual({"hwnd": 42, "process": "browser.exe", "title": "Catalog", "state": "active"},
                             response.json()["windows"][0])
            self.assertEqual("alpha", request.await_args.kwargs["line"])
            denied = await self.client.post("/api/conversations/beta/screen-windows",
                                            headers=self.machine("b"))
            self.assertEqual(403, denied.status_code)
            self.assertEqual(1, request.await_count)
        rows = self.db._exec("SELECT entry FROM screen_control_audit WHERE conv_id='alpha'").fetchall()
        self.assertTrue(any("list" in row["entry"] and "listed 1" in row["entry"] for row in rows))

    async def test_helper_cannot_grant_standing_access_to_an_unowned_line(self):
        await self.offer("target-request")
        await self.hub.window_grants.from_helper(self.device, {
            "type": "window_grant", "request_id": "grant-request", "grant_id": "foreign-grant",
            "line_id": "beta", "targets_request_id": "target-request", "hwnd": 42,
            "title": "Catalog", "process": "browser.exe", "standing_access": True,
        })
        self.assertFalse(self.sent[-1]["ok"])
        self.assertIn("not owned", self.sent[-1]["error"])

    async def test_attach_creates_a_normal_line_grant_and_a_line_audit(self):
        async def attach(device, kind, **fields):
            self.assertTrue(device["window_access_enabled"])
            self.assertEqual("attach_window", kind)
            await self.grant_line("alpha", "Catalog", "grant-1", 42, standing_access=True)
            return {"ok": True, "window": "grant-1", "title": "Catalog"}

        with patch.object(self.hub.standing_windows, "request", side_effect=attach):
            response = await self.client.post("/api/conversations/alpha/screen-attach-window",
                json={"window": "42", "reason": "Update the visible catalog description"},
                headers=self.machine("a"))
        self.assertEqual(200, response.status_code, response.text)
        grant = self.db._exec("SELECT * FROM screen_line_window_grants WHERE id='grant-1'").fetchone()
        self.assertEqual("alpha", grant["conv_id"])
        self.assertTrue(any("granted" in row["entry"] for row in self.db._exec(
            "SELECT entry FROM screen_control_audit WHERE conv_id='alpha'").fetchall()))
        bodies = [row["body"] for row in self.db.list_messages("alpha")]
        self.assertEqual(1, sum("Agents on this line are using window access" in body for body in bodies))
        self.assertFalse(any("Window access audit" in body for body in bodies))


class StandingCallCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pause_revokes_shares_control_calls_and_disconnects(self):
        from partyline_helper.screen_access_toggle import pause_windows

        session = SimpleNamespace(
            status=SimpleNamespace(window_access_enabled=True, changed=Mock()),
            send=AsyncMock(), stop=AsyncMock(),
            window=SimpleNamespace(revoke=Mock()),
            windows=SimpleNamespace(revoke_all=Mock(), close=AsyncMock()),
            window_task=SimpleNamespace(close=AsyncMock()),
            control=SimpleNamespace(end=Mock()), worker=None,
            tools=SimpleNamespace(end=AsyncMock()),
            socket=SimpleNamespace(close=AsyncMock()),
        )
        session.window_access_enabled = True
        session.window_task.cancel = Mock()
        session.disconnect_requested = False
        with patch("partyline_helper.screen_access_toggle.set_enabled", return_value=False):
            await pause_windows(session)
        session.stop.assert_awaited_once_with("access paused")
        session.window.revoke.assert_called_once_with("access paused")
        session.windows.revoke_all.assert_called_once_with()
        session.window_task.close.assert_awaited_once()
        session.windows.close.assert_awaited_once()
        session.tools.end.assert_awaited_once_with("access paused")
        session.socket.close.assert_awaited_once_with(code=1000, reason="window access paused")
        self.assertTrue(session.disconnect_requested)
        self.assertFalse(session.window_access_enabled)

    async def test_attach_refuses_line_outside_helper_owner_tree_and_releases_marker(self):
        from partyline_helper.window_standing_attach import attach

        row = {"hwnd": 12, "pid": 4, "marker": "lifetime", "process": "chrome.exe",
               "title": "Catalog", "id": "12:tab"}
        audit, send = SimpleNamespace(append=Mock()), AsyncMock()
        session = SimpleNamespace(window_access_enabled=True, standing_window_rows={"12:tab": row},
                                  window_access_audit=audit, send=send)
        shares = SimpleNamespace(session=session, generation=0,
                                 request=AsyncMock(return_value={"request_id": "targets",
                                                                "lines": [{"line_id": "elsewhere"}]}))
        message = {"request_id": "attach-1", "window": "12:tab", "line": "elsewhere",
                   "line_id": "elsewhere", "agent": "worker"}
        with patch("partyline_helper.uia_window_identity.unmark") as unmark:
            await attach(shares, message)
        unmark.assert_called_once_with(row)
        shares.request.assert_awaited_once_with("list_share_targets")
        send.assert_awaited_once()
        self.assertFalse(any(call.args[0] == "window_grant" for call in shares.request.await_args_list))

    async def test_pause_cancels_a_pending_discovery_and_answers_server(self):
        started = asyncio.Event()

        class Audit:
            def __init__(self):
                self.rows = []

            def append(self, *row):
                self.rows.append(row)

        class Status:
            def __init__(self):
                self.calls = {}

            def begin_window_call(self, line, agent):
                self.calls[1] = (line, agent)
                return 1

            def end_window_call(self, ident):
                self.calls.pop(ident)

        session = SimpleNamespace(window_access_enabled=True, status=Status(),
                                  window_access_audit=Audit(), send=AsyncMock())
        from partyline_helper.window_shares import WindowShares
        shares = WindowShares(session)

        async def pending(_shares, _message):
            started.set()
            await asyncio.Event().wait()

        with patch("partyline_helper.window_standing_calls._call", side_effect=pending):
            task = shares.spawn_standing({"type": "screen_windows", "request_id": "r1",
                                          "line": "line", "line_name": "Line", "agent": "worker"})
            await started.wait()
            shares.revoke_all()
            await task

        session.send.assert_awaited_once_with("screen_windows_result", request_id="r1", windows=[],
                                              error="window access was paused")
        self.assertEqual("cancelled: access paused", session.window_access_audit.rows[0][-1])
        self.assertFalse(session.status.calls)
