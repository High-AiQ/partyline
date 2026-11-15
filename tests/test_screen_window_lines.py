"""Multiple standing roots, migration, owner-only options and truthful indicators."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.screen_device_access import standing_devices, standing_roots
from partyline.screen_snapshot import owner_indicators
from partyline.screen_window_line_routes import picker_options
from tests.window_grant_fixtures import WindowGrantFixture


class WindowLinesTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    def url(self):
        return f"/api/screen/devices/{self.device['id']}/window-access-lines"

    async def select(self, lines, headers=None):
        return await self.client.put(self.url(), json={"conv_ids": lines},
                                     headers=headers or self.human(self.owner))

    def child(self, ident, parent):
        self.db.create_conversation(ident, ident.title())
        self.db._exec("UPDATE conversations SET parent_id=? WHERE id=?", (parent, ident))

    async def test_add_is_nonrevoking_remove_revokes_only_removed_subtree(self):
        self.child("child", "alpha")
        await self.grant("a", standing_access=True)
        self.assertEqual(200, (await self.select(["alpha", "beta"])).status_code)
        await self.grant("b", grant_id="beta-grant", hwnd=11, standing_access=True)
        await self.grant_line("child", grant_id="child-grant", hwnd=12, standing_access=True)
        await self.grant_line("alpha", grant_id="explicit", hwnd=13)
        self.sent.clear()
        self.assertEqual(200, (await self.select(["beta"])).status_code)
        self.assertCountEqual(["g1", "child-grant"],
                             [m["grant_id"] for m in self.sent if m["type"] == "revoke_window"])
        self.assertCountEqual(["explicit", "beta-grant"], [row["id"] for row in
            self.db._exec("SELECT id FROM screen_line_window_grants").fetchall()])
        self.assertEqual([], standing_devices(self.hub, "child"))
        self.assertEqual([self.device], standing_devices(self.hub, "beta"))

    async def test_removing_ancestor_revokes_overlap_but_retained_child_can_attach_again(self):
        self.child("child", "alpha")
        await self.select(["alpha", "child", "beta"])
        await self.grant_line("child", grant_id="child-grant", standing_access=True)
        await self.grant_line("beta", grant_id="beta-grant", hwnd=11, standing_access=True)
        self.sent.clear()
        await self.select(["child", "beta"])
        self.assertEqual(["child-grant"], [m["grant_id"] for m in self.sent if m["type"] == "revoke_window"])
        self.assertEqual([self.device], standing_devices(self.hub, "child"))
        self.assertIsNotNone(self.db._exec("SELECT id FROM screen_line_window_grants WHERE id='beta-grant'")
                            .fetchone())
        result = await self.grant_line("child", grant_id="new-child-grant", standing_access=True)
        self.assertTrue(result["ok"])

    async def test_adding_and_idempotent_set_do_not_notify_or_revoke(self):
        await self.grant("a", standing_access=True)
        self.sent.clear()
        for lines in (["alpha", "beta"], ["beta", "alpha", "alpha"]):
            self.assertEqual(200, (await self.select(lines)).status_code)
        self.assertFalse(any(m["type"] == "revoke_window" for m in self.sent))
        self.assertEqual({"alpha", "beta"}, standing_roots(self.db, self.device))
        self.assertTrue(self.db._exec("SELECT id FROM screen_line_window_grants").fetchone())

    async def test_all_removed_grants_deleted_before_yield_and_stale_offer_denied(self):
        self.child("child", "alpha")
        await self.grant("a", standing_access=True)
        await self.grant_line("child", grant_id="child-grant", hwnd=11, standing_access=True)
        await self.offer("stale")
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked_notice(*_):
            entered.set()
            await release.wait()

        with patch("partyline.screen_window_grants.announce", side_effect=blocked_notice):
            task = asyncio.create_task(self.select(["beta"]))
            try:
                await entered.wait()
                self.assertFalse(self.db._exec("SELECT id FROM screen_line_window_grants").fetchall())
                await self.hub.window_grants.from_helper(self.device, {
                    "type": "window_grant", "request_id": "late", "targets_request_id": "stale",
                    "line_id": "alpha", "grant_id": "late", "hwnd": 20, "title": "Late",
                    "process": "editor", "standing_access": True})
                self.assertFalse(self.sent[-1]["ok"])
            finally:
                release.set()
                await task

    async def test_removal_discards_discovery_and_attach_responses_already_in_flight(self):
        for operation, payload in (("screen-windows", None),
                                   ("screen-attach-window", {"window": "42", "reason": "Review document"})):
            await self.select(["alpha"])
            entered, release = asyncio.Event(), asyncio.Event()

            async def request(*args, entered=entered, release=release, **kwargs):
                entered.set()
                await release.wait()
                return {"windows": [{"title": "Secret"}], "ok": True, "window": "late"}

            with patch.object(self.hub.standing_windows, "request", side_effect=request):
                task = asyncio.create_task(self.client.post(f"/api/conversations/alpha/{operation}",
                    json=payload, headers=self.machine("a")))
                await entered.wait()
                await self.select([])
                release.set()
                response = await task
                self.assertEqual(403, response.status_code)
                self.assertNotIn("Secret", response.text)

    async def test_multiple_roots_ancestors_archival_and_unknown_owner(self):
        self.child("child", "alpha")
        self.child("grandchild", "child")
        await self.select(["alpha", "beta"])
        self.assertTrue(standing_devices(self.hub, "grandchild"))
        self.assertFalse(standing_devices(self.hub, "empty"))
        self.assertFalse(standing_devices(self.hub, "missing"))
        self.db._exec("UPDATE conversations SET archived_at=1 WHERE id='child'")
        self.assertFalse(standing_devices(self.hub, "grandchild"))
        self.assertTrue(standing_devices(self.hub, "beta"))
        for owner in (None, 999999, self.other_user["id"]):
            self.assertFalse(standing_devices(SimpleNamespace(runtime=self.runtime,
                devices={"d": {**self.device, "owner_id": owner}}), "beta"))
        self.assertEqual([], standing_devices(SimpleNamespace(), "alpha"))

    async def test_owner_only_routes_validate_without_partial_changes(self):
        self.assertEqual(403, (await self.select(["beta"], self.machine("a"))).status_code)
        self.assertEqual(404, (await self.select(["beta"], self.human(self.other_user))).status_code)
        self.assertEqual(404, (await self.select(["beta", "missing"])).status_code)
        self.db._exec("UPDATE conversations SET archived_at=1 WHERE id='beta'")
        self.assertEqual(409, (await self.select(["beta"])).status_code)
        self.assertEqual({"alpha"}, standing_roots(self.db, self.device))
        self.assertEqual(200, (await self.select([])).status_code)

    async def test_picker_live_top_level_and_selected_idle_and_owner_visibility(self):
        self.child("child", "alpha")
        self.db.add_attachment("child", "child", "child", "raw", ["shell"], "/tmp", "child")
        response = await self.client.get(self.url(), headers=self.human(self.owner))
        self.assertEqual({"alpha", "beta"}, {r["id"] for r in response.json()["lines"]})
        await self.select(["alpha", "empty"])
        self.db.set_attachment_status("a", "detached", "activation-a")
        self.db.set_attachment_status("peer", "exited", "activation-peer")
        response = await self.client.get(self.url(), headers=self.human(self.owner))
        self.assertEqual({"alpha", "beta", "empty"}, {r["id"] for r in response.json()["lines"]})
        self.assertEqual(403, (await self.client.get(self.url(), headers=self.machine("b"))).status_code)
        response = await self.client.get(self.url(), headers=self.human(self.other_user))
        self.assertEqual(404, response.status_code)
        principal = Principal(kind="user", name="owner", user_id=self.owner["id"])
        with patch("partyline.screen_window_line_routes.allows", side_effect=lambda d, p, i, c: i == "beta"):
            self.assertEqual([{"id": "beta", "name": "Beta"}], picker_options(self.db, principal, {"empty"}))

    async def test_indicators_online_enabled_subtree_active_grants_and_owner_scoping(self):
        self.child("child", "alpha")
        items = owner_indicators(self.hub, self.owner["id"])
        self.assertEqual({"alpha", "child"}, {i["conv_id"] for i in items})
        self.assertEqual({"standing"}, {i["kind"] for i in items})
        await self.grant("a", standing_access=True)
        await self.grant("b", grant_id="explicit", hwnd=11)
        items = owner_indicators(self.hub, self.owner["id"])
        self.assertEqual({"alpha", "beta"}, {i["conv_id"] for i in items if i["kind"] == "window"})
        self.assertEqual([], owner_indicators(self.hub, self.other_user["id"]))
        self.device["window_access_enabled"] = False
        self.assertEqual(["beta"], [i["conv_id"] for i in owner_indicators(self.hub, self.owner["id"])])
        self.hub.devices.clear()
        self.assertEqual([], owner_indicators(self.hub, self.owner["id"]))

    async def test_toggle_and_hierarchy_changes_push_new_server_indicators(self):
        from partyline.contracts import ConversationsChangedEvent
        from partyline.screen_standing import update_mirror

        socket = Mock(screen_owner_id=self.owner["id"], send_json=AsyncMock())
        self.runtime.sockets["alpha"] = {socket}
        self.runtime.screen_hub = self.hub
        await update_mirror(self.hub, self.device, {"type": "window_access_changed", "enabled": False})
        self.assertEqual([], socket.send_json.call_args.args[0]["indicators"])
        await update_mirror(self.hub, self.device, {"type": "window_access_changed", "enabled": True})
        self.assertEqual("standing", socket.send_json.call_args.args[0]["indicators"][0]["kind"])
        self.child("child", "alpha")
        await self.runtime.broadcast_all(ConversationsChangedEvent())
        snapshots = [c.args[0] for c in socket.send_json.call_args_list
                     if c.args[0]["type"] == "screen_snapshot"]
        self.assertEqual({"alpha", "child"}, {i["conv_id"] for i in snapshots[-1]["indicators"]})
        socket.send_json.side_effect = RuntimeError("closed")
        await self.runtime.broadcast_all(ConversationsChangedEvent())

    async def test_migration_copies_exact_old_binding_once_and_never_resurrects_removed_lines(self):
        ident = self.device["id"]
        self.db._exec("DELETE FROM screen_device_window_lines")
        self.db._exec("UPDATE screen_device_window_access SET owner_conv_id='alpha' WHERE device_id=?",
                      (ident,))
        for expected in ({"alpha"}, set()):
            reopened = Db(self.db.path)
            try:
                self.assertEqual(expected, standing_roots(reopened, self.device))
                row = reopened._exec("SELECT owner_conv_id FROM screen_device_window_access").fetchone()
                self.assertIsNone(row[0])
                reopened._exec("DELETE FROM screen_device_window_lines")
            finally:
                reopened.close()

    async def test_migration_does_not_approve_unknown_owner_or_absent_binding(self):
        self.db._exec("DELETE FROM screen_device_window_lines")
        self.db._exec("UPDATE screen_device_window_access SET owner_conv_id='alpha'")
        self.db._exec("PRAGMA foreign_keys=OFF")
        self.db._exec("UPDATE screen_devices SET owner_id=987654")
        reopened = Db(self.db.path)
        try:
            self.assertFalse(reopened._exec("SELECT * FROM screen_device_window_lines").fetchall())
        finally:
            reopened.close()
