"""Update announcements pause real HTTP tools, preserve grants and resume without polling."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from partyline_helper import __version__
from partyline.screen_helper_updates import HelperUpdating, PAUSED
from partyline.screen_protocol import HelperHello
from tests.window_grant_fixtures import WindowGrantFixture


class HelperUpdatesTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        self.hub.updates.close()
        await super().asyncTearDown()

    async def pause(self):
        await self.grant("a")
        await self.hub.updates.receive(self.device, {"type": "helper_updating", "version": __version__})

    async def test_pause_returns_clear_answers_for_read_action_snapshot_click_and_eval(self):
        await self.pause()
        self.assertTrue(self.hub.updates.paused(self.device["id"]))
        self.assertEqual((await self.read("a")).json(), PAUSED)
        self.assertEqual((await self.act("a")).json(), PAUSED)
        for path, body in (("screen-window-snapshot", None),
                           ("screen-control/window-click", {"snapshot": "old", "x": 1, "y": 1}),
                           ("screen-eval", {"expression": "1"})):
            response = await self.client.post("/api/conversations/alpha/" + path,
                headers=self.machine("a"), json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "paused")
        # Still paused while the helper is offline; the grant remains authorized to this line only.
        await self.hub.window_grants.disconnected(self.device["id"])
        self.hub.devices.pop(self.device["id"])
        self.assertEqual((await self.read("a")).json()["reason"], "helper updating")
        self.assertEqual((await self.read("b")).status_code, 403)

    async def test_inflight_exchange_finishes_as_paused_and_announcement_is_acknowledged(self):
        await self.grant("a")
        future = asyncio.get_running_loop().create_future()
        self.hub.elements.waiters["pending"] = (self.device["id"], future)
        await self.hub.updates.receive(self.device, {"type": "helper_updating", "version": __version__})
        with self.assertRaises(HelperUpdating):
            await future
        self.assertIn({"type": "helper_update_paused"}, self.sent)

    async def test_recovery_resumes_retained_grant_and_posts_line_notice(self):
        await self.pause()
        hello = HelperHello(type="hello", protocol=1, helper_version=__version__, device_name="Computer",
                            os="test", monitors=[], update_recovery=True, auto_update=True)
        await self.hub.updates.connected(self.device, hello)
        restore = next(row for row in self.sent if row["type"] == "helper_update_restore")
        self.assertEqual([row["id"] for row in restore["grants"]], ["g1"])
        self.device["helper_version"] = __version__
        await self.hub.updates.receive(self.device, {"type": "helper_update_restored", "grants": ["g1"]})
        self.assertFalse(self.hub.updates.paused(self.device["id"]))
        self.assertEqual((await self.read("a")).status_code, 200)
        messages = self.db.list_messages("alpha")
        self.assertTrue(any(f"helper updated to {__version__}; window access resumed" in m["body"]
                            for m in messages))

    async def test_stale_grants_are_dropped_and_failed_update_lifts_pause(self):
        await self.pause()
        await self.hub.updates.receive(self.device,
            {"type": "helper_update_restored", "grants": [], "failed": True})
        self.assertFalse(self.hub.updates.paused(self.device["id"]))
        self.assertEqual((await self.read("a")).status_code, 403)
        rows = self.db._exec("SELECT detail FROM screen_helper_update_audit").fetchall()
        self.assertTrue(any("failed" in row["detail"] for row in rows))

    async def test_deadline_is_one_event_and_failure_has_no_retry(self):
        await self.pause()
        self.hub.updates.close()
        loop = asyncio.get_running_loop()
        scheduled = []
        with patch.object(loop, "call_later", side_effect=lambda delay, callback:
                          scheduled.append((delay, callback)) or SimpleNamespace(cancel=lambda: None)):
            self.hub.updates.arm(self.device["id"], 0)
        self.assertEqual(len(scheduled), 1)
        task = scheduled[0][1]()
        await task
        self.assertIsNone(self.hub.updates.paused(self.device["id"]))
        self.assertEqual(len(scheduled), 1)

    async def test_published_push_is_authorized_versioned_and_reaches_connected_helpers(self):
        url = "/api/screen/helper-release-published"
        self.assertEqual((await self.client.post(url, json={"version": __version__},
                          headers=self.machine("a"))).status_code, 403)
        self.assertEqual((await self.client.post(url, json={"version": "0.0.1"},
                          headers=self.human(self.owner))).status_code, 409)
        result = await self.client.post(url, json={"version": __version__}, headers=self.human(self.owner))
        self.assertEqual(result.json(), {"sent": 1})
        event = self.sent[-1]
        self.assertEqual(event["type"], "helper_release_published")
        self.assertTrue(event["helper_update"]["available"])
        self.assertIn(f"helper-v{__version__}", event["helper_update"]["url"])

    async def test_person_only_setting_persists_offline_and_pending_wins_on_reconnect(self):
        url = f"/api/screen/devices/{self.device['id']}/auto-update"
        for headers in (self.machine("a"), self.human(self.other_user)):
            self.assertIn((await self.client.put(url, json={"enabled": True}, headers=headers)).status_code,
                          (403, 404))
        self.hub.devices.pop(self.device["id"])
        self.assertEqual((await self.client.put(url, json={"enabled": True},
                         headers=self.human(self.owner))).json(), {"ok": True})
        listing = await self.client.get("/api/screen/devices", headers=self.human(self.owner))
        self.assertTrue(listing.json()["devices"][0]["auto_update"])
        self.hub.devices[self.device["id"]] = self.device
        hello = HelperHello(type="hello", protocol=1, helper_version="1.5.0", device_name="Computer",
                            os="test", monitors=[], auto_update=False, update_check=True)
        await self.hub.updates.connected(self.device, hello)
        self.assertEqual(self.sent[-1], {"type": "set_auto_update", "enabled": True})
        await self.hub.updates.receive(self.device, {"type": "auto_update_changed", "enabled": False})
        self.assertEqual(self.sent[-1], {"type": "set_auto_update", "enabled": True})
        await self.hub.updates.receive(self.device, {"type": "auto_update_changed", "enabled": True})
        row = self.db._exec("SELECT * FROM screen_helper_preferences").fetchone()
        self.assertEqual((row["enabled"], row["pending"]), (1, 0))

    async def test_connect_mirrors_local_preference_and_rejects_downgrade_announcements(self):
        hello = HelperHello(type="hello", protocol=1, helper_version="1.5.0", device_name="Computer",
                            os="test", monitors=[], auto_update=True, update_check=True)
        await self.hub.updates.connected(self.device, hello)
        self.assertTrue(self.sent[-1]["helper_update"]["available"])
        self.device["helper_version"] = __version__
        with self.assertRaises(ValueError):
            await self.hub.updates.receive(self.device, {"type": "helper_updating", "version": __version__})

    async def test_deadline_revokes_offline_grants_and_late_recovery_does_not_open_another_pause(self):
        await self.pause()
        ident = self.device["id"]
        self.hub.devices.pop(ident)
        await self.hub.updates.finish(ident, failed=True, expired=True)
        self.assertEqual(self.db._exec("SELECT id FROM screen_line_window_grants").fetchall(), [])
        self.assertNotIn("g1", self.hub.window_grants.known)
        notices = [row["body"] for row in self.db.list_messages("alpha")
                   if "helper update failed" in row["body"]]
        self.assertTrue(any("window access ended" in text for text in notices))
        self.assertFalse(any("resumed" in text for text in notices))
        self.hub.devices[ident] = self.device
        hello = HelperHello(type="hello", protocol=1, helper_version="1.5.0", device_name="Computer",
                            os="test", monitors=[], update_recovery=True)
        await self.hub.updates.connected(self.device, hello)
        self.assertIsNone(self.hub.updates.paused(ident))
        self.assertEqual(self.sent[-1], {"type": "helper_update_restore", "grants": []})
        await self.hub.updates.receive(self.device,
            {"type": "helper_update_restored", "grants": [], "failed": True})
        after = [row["body"] for row in self.db.list_messages("alpha")
                   if "helper update failed" in row["body"]]
        self.assertEqual(after, notices)

    async def test_server_deadline_covers_the_supervisor_rollback_and_final_reconnect(self):
        from partyline_helper.update_timing import SERVER_DEADLINE, SUPERVISOR_BUDGET, RECONNECT
        self.assertGreater(SERVER_DEADLINE, SUPERVISOR_BUDGET + RECONNECT)

    async def test_standing_list_attach_and_granted_calls_are_paused_and_audited_when_offline(self):
        await self.pause()
        self.hub.devices.pop(self.device["id"])
        for path, body, call in (("screen-windows", None, "list"),
                                 ("screen-attach-window", {"window": "10", "reason": "Inspect"}, "attach"),
                                 ("screen-elements", None, "uia_read")):
            response = await self.client.post("/api/conversations/alpha/" + path,
                json=body, headers=self.machine("a"))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "paused")
            rows = self.db._exec("SELECT entry FROM screen_control_audit WHERE agent='a'").fetchall()
            self.assertTrue(any(call in row["entry"] and "paused: helper updating" in row["entry"]
                                for row in rows))

    async def test_unchanged_reconnect_and_setting_ack_do_not_duplicate_the_change_audit(self):
        hello = HelperHello(type="hello", protocol=1, helper_version="1.5.0", device_name="Computer",
                            os="test", monitors=[], auto_update=True)
        for _ in range(3):
            await self.hub.updates.connected(self.device, hello)
        rows = self.db._exec("SELECT id FROM screen_helper_update_audit").fetchall()
        self.assertEqual(len(rows), 1)
        await self.client.put(f"/api/screen/devices/{self.device['id']}/auto-update",
                             json={"enabled": False}, headers=self.human(self.owner))
        await self.hub.updates.receive(self.device, {"type": "auto_update_changed", "enabled": False})
        rows = self.db._exec("SELECT id FROM screen_helper_update_audit").fetchall()
        self.assertEqual(len(rows), 2)

    async def test_deadline_removes_persisted_grants_even_after_the_memory_map_is_lost(self):
        await self.pause()
        self.hub.devices.pop(self.device["id"])
        self.hub.window_grants.known.clear()
        await self.hub.updates.finish(self.device["id"], failed=True, expired=True)
        self.assertEqual(self.db._exec("SELECT id FROM screen_line_window_grants").fetchall(), [])

    async def test_offline_expiry_pushes_a_final_snapshot_with_the_pause_lifted(self):
        from unittest.mock import AsyncMock
        await self.pause()
        self.hub.devices.pop(self.device["id"])
        states = []
        async def changed(device, online):
            states.append((online, bool(self.hub.updates.paused(device["id"]))))
        with patch.object(self.hub, "_device_event", AsyncMock(side_effect=changed)):
            await self.hub.updates.finish(self.device["id"], failed=True, expired=True)
        self.assertEqual(states[-1], (False, False))
