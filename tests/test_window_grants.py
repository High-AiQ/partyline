"""Cross-line window authorization and lifecycle, with event-driven helper responses."""
import unittest
from unittest.mock import AsyncMock, patch

from partyline.auth_guard import Principal
from partyline.screen_grants import device_grants, resolve_window, window_share_indicators
from partyline.screen_window_grants import share_targets
from tests.window_grant_fixtures import WindowGrantFixture


class WindowGrantTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def test_two_windows_one_process_ambiguity_and_snapshot_isolation(self):
        self.assertTrue((await self.grant("a"))["ok"])
        self.assertTrue((await self.grant("a", "Browser", "g2", 20))["ok"])
        response = await self.read("a")
        self.assertEqual(409, response.status_code)
        self.assertIn("g1: Editor", response.text)
        self.assertIn("g2: Browser", response.text)
        self.assertEqual(409, (await self.act("a")).status_code)
        for title, grant in (("Editor", "g1"), ("g2", "g2")):
            response = await self.read("a", title)
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(grant, response.json()["window"])
            self.assertEqual(grant + "-snapshot", response.json()["snapshot_id"])
            self.assertEqual(200, (await self.act("a", title)).status_code)
        self.assertEqual("g2", self.sent[-1]["grant_id"])

    async def test_different_lines_other_process_refused_holder_named(self):
        await self.grant("a")
        await self.grant("b", "Browser", "g2", 20)
        for ident, _own, foreign, holder in (("a", "g1", "g2", "b"), ("b", "g2", "g1", "a")):
            self.assertEqual(200, (await self.read(ident)).status_code)
            self.assertEqual(200, (await self.act(ident)).status_code)
            for call in (self.read, self.act):
                response = await call(ident, foreign)
                self.assertEqual(403, response.status_code)
                self.assertIn("@" + holder, response.text)
        response = await self.read("peer")
        self.assertEqual(403, response.status_code)
        self.assertIn("no window is shared with you", response.text)

    async def test_stopping_one_and_detaching_target_only_end_own_grants(self):
        await self.grant("a")
        await self.grant("a", "Browser", "g2", 20)
        await self.grant("b", "Terminal", "g3", 30)
        await self.hub.window_grants.from_helper(self.device, {"type": "window_revoked", "grant_id": "g1"})
        self.assertEqual("g2", (await self.read("a")).json()["window"])
        self.db.set_attachment_status("a", "detached", "activation-a")
        await self.hub.window_grants.expire()
        self.assertEqual(401, (await self.read("a")).status_code)
        self.assertEqual("g3", (await self.read("b")).json()["window"])
        self.assertEqual(["g3"], [g["id"] for g in device_grants(self.db, self.device["id"])])
        self.assertIn({"type": "revoke_window", "grant_id": "g2"}, self.sent)

    async def test_owner_revoke_and_machine_cannot_set_or_revoke(self):
        await self.grant("a")
        url = "/api/screen/window-grants/g1"
        self.assertEqual(403, (await self.client.delete(url, headers=self.machine("a"))).status_code)
        response = await self.client.delete(url, headers=self.human(self.other_user))
        self.assertEqual(404, response.status_code)
        self.assertEqual(405, (await self.client.put(url, headers=self.machine("a"), json={})).status_code)
        self.assertEqual(200, (await self.client.delete(url, headers=self.human(self.owner))).status_code)
        self.assertEqual(403, (await self.read("a")).status_code)

    async def test_target_groups_are_live_owner_visible_and_revalidated(self):
        groups = share_targets(self.db, self.owner["id"])
        self.assertEqual({"alpha", "beta"}, {g["line_id"] for g in groups})
        self.assertEqual({"a", "peer"}, {p["attachment_id"] for g in groups if g["line_id"] == "alpha"
                                        for p in g["processes"]})
        with patch("partyline.screen_window_grants.visible_conversation_ids", return_value={"beta"}):
            self.assertEqual(["beta"], [g["line_id"] for g in share_targets(self.db, self.owner["id"])])
            self.assertFalse((await self.grant("a"))["ok"])
        self.assertFalse((await self.grant("ended"))["ok"])
        self.assertFalse((await self.grant("a", runtime_owner="obsolete"))["ok"])
        self.assertFalse((await self.grant("a", hwnd=0))["ok"])
        self.assertEqual([], share_targets(self.db, 99999))
        await self.hub.window_grants.from_helper(
            self.device, {"type": "list_share_targets", "request_id": "list"})
        self.assertEqual("share_targets", self.sent[-1]["type"])

    async def test_scope_survives_races_but_not_resume_or_disconnect(self):
        await self.grant("a")
        async def detach_after_dispatch(message):
            await self.receive(message)
            self.db.set_attachment_status("a", "exited", "activation-a")
        self.device["socket"].send_json = detach_after_dispatch
        self.assertEqual(403, (await self.read("a")).status_code)
        self.db.claim_attachment("a", "next-activation")
        self.assertEqual(403, (await self.read("a")).status_code)
        self.device["socket"].send_json = self.receive
        await self.grant("b", "Browser", "g2", 20)
        await self.hub.window_grants.disconnected(self.device["id"])
        self.assertEqual(403, (await self.read("b")).status_code)

    async def test_owner_indicators_and_same_window_replacement(self):
        await self.grant("a")
        await self.grant("b", "Editor", "g2", 10)
        self.assertEqual(403, (await self.read("a")).status_code)
        self.assertEqual(200, (await self.read("b")).status_code)
        indicators = window_share_indicators(self.db, self.owner["id"])
        self.assertEqual([{"conv_id": "beta", "device_name": "Computer", "kind": "window",
                           "label": "reading Editor for @b"}], indicators)
        self.assertEqual([], window_share_indicators(self.db, self.other_user["id"]))
        principal = Principal(kind="user", name="other", user_id=self.other_user["id"])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            resolve_window(self.hub, principal)

    async def test_actions_keep_rate_limits_per_window(self):
        await self.grant("a")
        self.hub.control.clock = lambda: 0
        for _ in range(self.hub.control.limits.per_second):
            self.assertEqual(200, (await self.act("a")).status_code)
        response = await self.act("a")
        self.assertEqual(409, response.status_code)
        self.assertIn("rate limit", response.text)

    async def test_revoke_survives_helper_disconnect(self):
        await self.grant("a")
        self.device["socket"].send_json = AsyncMock(side_effect=RuntimeError("closed"))
        response = await self.client.delete("/api/screen/window-grants/g1", headers=self.human(self.owner))
        self.assertEqual(200, response.status_code)
        self.assertEqual(403, (await self.read("a")).status_code)
