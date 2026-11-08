"""Secret-free picker data, owner isolation and deterministic grant races."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.auth_guard import Principal
from partyline.screen_grants import device_grants, resolve_window
from tests.window_grant_fixtures import WindowGrantFixture


class WindowBoundaryTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    def grant_message(self, ident="a", grant_id="g1"):
        return {"type": "window_grant", "request_id": "grant", "targets_request_id": "targets",
                "attachment_id": ident, "grant_id": grant_id, "title": "Editor", "process": "app", "hwnd": 10}

    async def offer(self):
        await self.hub.window_grants.from_helper(
            self.device, {"type": "list_share_targets", "request_id": "targets"})

    async def test_activation_secrets_never_appear_in_any_response(self):
        await self.offer()
        await self.hub.window_grants.from_helper(self.device, self.grant_message())
        responses = list(self.sent)
        for line in ("alpha", "beta", "paired"):
            response = await self.client.get("/api/screen/devices", params={"conv_id": line},
                                             headers=self.human(self.owner))
            self.assertEqual(200, response.status_code)
            self.assertEqual("g1", response.json()["devices"][0]["window_grants"][0]["id"])
            responses.append(response.json())
        response = await self.client.get("/api/screen/active-indicators", headers=self.human(self.owner))
        self.assertEqual("window", response.json()["indicators"][0]["kind"])
        self.assertEqual("alpha", response.json()["indicators"][0]["conv_id"])
        responses.append(response.json())
        responses.append(device_grants(self.db, self.device["id"]))
        responses.append((await self.read("a")).json())
        responses.append((await self.act("a")).json())
        text = json.dumps(responses)
        self.assertNotIn("runtime_owner", text)
        for line in ("alpha", "beta", "empty"):
            for att in self.db.list_attachments(line):
                self.assertNotIn(att["runtime_owner"], text)
        stored = self.db._exec("SELECT runtime_owner FROM screen_window_grants WHERE id='g1'").fetchone()
        self.assertEqual("activation-a", stored["runtime_owner"])

    async def test_picker_offer_cannot_follow_a_replaced_activation(self):
        await self.offer()
        self.db.set_attachment_status("a", "detached", "activation-a")
        self.db.claim_attachment("a", "new-private-secret")
        await self.hub.window_grants.from_helper(self.device, self.grant_message())
        self.assertFalse(self.sent[-1]["ok"])
        self.assertFalse(device_grants(self.db, self.device["id"]))
        await self.offer()
        await self.hub.window_grants.from_helper(self.device, self.grant_message())
        self.assertTrue(self.sent[-1]["ok"])
        self.assertNotIn("new-private-secret", json.dumps(self.sent))

    async def test_failed_insert_keeps_old_grant_and_sends_no_revoke(self):
        await self.grant("a")
        self.db._exec("CREATE TRIGGER reject_replacement BEFORE INSERT ON screen_window_grants "
                      "WHEN NEW.id='replacement' BEGIN SELECT RAISE(ABORT,'failed insert'); END")
        response = await self.grant("b", grant_id="replacement")
        self.assertFalse(response["ok"])
        self.assertEqual(200, (await self.read("a")).status_code)
        self.assertFalse(any(message["type"] == "revoke_window" for message in self.sent))
        self.assertEqual(["g1"], list(self.hub.window_grants.known))

    async def test_owner_notifications_reach_only_that_account(self):
        owner, second_tab, other = Mock(), Mock(), Mock()
        for socket in (owner, second_tab, other):
            socket.send_json = AsyncMock()
        self.runtime.human_handles = {"alpha": {owner: ("old-owner-name", "one"), other: ("owner", "two")},
                                      "beta": {second_tab: ("old-owner-name", "three")}}
        for socket in (owner, second_tab):
            socket.screen_owner_id = self.owner["id"]
        other.screen_owner_id = self.other_user["id"]
        self.runtime.sockets = {"alpha": {owner, other}, "beta": {second_tab}}
        await self.grant("a")
        for socket in (owner, second_tab):
            socket.send_json.assert_awaited_once()
            self.assertEqual(self.device["id"], socket.send_json.await_args.args[0]["device_id"])
        other.send_json.assert_not_awaited()

    async def test_disconnected_and_replaced_sockets_cannot_register_grants(self):
        await self.offer()
        self.hub.devices.pop(self.device["id"])
        await self.hub.window_grants.disconnected(self.device["id"])
        await self.hub.window_grants.from_helper(self.device, self.grant_message())
        self.assertFalse(device_grants(self.db, self.device["id"]))
        self.hub.devices[self.device["id"]] = {
            **self.device, "socket": SimpleNamespace(send_json=AsyncMock())}
        await self.hub.window_grants.from_helper(self.device, self.grant_message())
        self.assertFalse(device_grants(self.db, self.device["id"]))

    async def test_action_is_checked_before_dispatch_and_late_success_is_not_a_refusal(self):
        await self.grant("a")
        with patch.object(self.hub.window_grants, "spend", side_effect=lambda _: self.db._exec(
                "DELETE FROM screen_window_grants WHERE id='g1'")):
            response = await self.act("a")
        self.assertEqual(403, response.status_code)
        self.assertFalse(any(m["type"] == "window_element_action" for m in self.sent))
        await self.grant("a", grant_id="g2")
        async def finish_then_end(message):
            await self.receive(message)
            self.db._exec("DELETE FROM screen_window_grants WHERE id='g2'")
        self.device["socket"].send_json = finish_then_end
        response = await self.act("a")
        self.assertEqual(200, response.status_code)
        self.assertEqual("completed", response.json()["status"])
        self.assertTrue(response.json()["grant_ended"])
        self.assertIn("performed", response.json()["note"])
        self.assertNotIn("elements", response.json())

    async def test_denials_name_relevant_holders_without_leaking_other_owners(self):
        await self.grant("a")
        first = self.device
        self.db.add_attachment("foreign", "beta", "private-holder", "raw", ["shell"],
                               "/tmp", "foreign-secret")
        code = self.hub.issue_pair_code(self.other_user["id"], "paired")
        ident, _, _, _ = self.hub.claim_pair_code(code, "Private computer", "test")
        self.device = {**first, "id": ident, "owner_id": self.other_user["id"], "name": "Private computer"}
        self.hub.devices[ident] = self.device
        await self.grant("foreign", title="Private title", grant_id="private")
        self.device = first
        response = await self.read("peer")
        self.assertIn("@a", response.text)
        self.assertNotIn("private-holder", response.text)
        for ident in ("a", "peer"):
            response = await self.read(ident, "private")
            self.assertEqual(403, response.status_code)
            self.assertNotIn("private-holder", response.text)
            self.assertNotIn("Private title", response.text)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as error:
            principal = Principal(kind="user", name="owner", user_id=self.owner["id"])
            resolve_window(self.hub, principal, "private")
        self.assertNotIn("private-holder", error.exception.detail)

    async def test_device_filter_cannot_change_a_machine_owner_context(self):
        await self.grant("a")
        first = self.device
        self.db.add_attachment("foreign", "alpha", "private-holder", "raw", ["shell"],
                               "/tmp", "foreign-secret")
        code = self.hub.issue_pair_code(self.other_user["id"], "paired")
        ident, _, _, _ = self.hub.claim_pair_code(code, "Private computer", "test")
        self.device = {**first, "id": ident, "owner_id": self.other_user["id"], "name": "Private computer"}
        self.hub.devices[ident] = self.device
        await self.grant("foreign", title="Private title", grant_id="private")
        self.device = first
        response = await self.client.post("/api/conversations/alpha/screen-elements",
            params={"device": "Private computer", "window": "private"}, headers=self.machine("a"))
        self.assertEqual(403, response.status_code)
        self.assertNotIn("private-holder", response.text)

    async def test_lost_action_acknowledgement_never_claims_the_action_was_refused(self):
        await self.grant("a")
        with patch.object(self.hub.elements, "exchange", side_effect=TimeoutError):
            response = await self.act("a")
        self.assertEqual(200, response.status_code)
        self.assertEqual("unconfirmed", response.json()["status"])
        self.assertIn("may have run", response.json()["note"])
        self.assertIn("Do not retry", response.json()["note"])

    async def test_owner_indicators_follow_grant_lifecycle_across_lines(self):
        await self.grant("a")
        await self.grant("b", "Browser", "g2", 20)
        url = "/api/screen/active-indicators"
        response = await self.client.get(url, headers=self.human(self.owner))
        indicators = response.json()["indicators"]
        self.assertEqual({"alpha", "beta"}, {g["conv_id"] for g in indicators})
        self.assertEqual({"window"}, {g["kind"] for g in indicators})
        response = await self.client.get(url, headers=self.human(self.other_user))
        self.assertEqual([], response.json()["indicators"])
        self.assertEqual(403, (await self.client.get(url, headers=self.machine("a"))).status_code)
        await self.client.delete("/api/screen/window-grants/g1", headers=self.human(self.owner))
        indicators = (await self.client.get(url, headers=self.human(self.owner))).json()["indicators"]
        self.assertEqual(["beta"], [g["conv_id"] for g in indicators])
        self.db.set_attachment_status("b", "exited", "activation-b")
        response = await self.client.get(url, headers=self.human(self.owner))
        self.assertEqual([], response.json()["indicators"])

    async def test_account_migration_repeats_safely_with_window_grants(self):
        from partyline.db import Db
        from partyline.screen_routes import register_screen_routes
        from fastapi import FastAPI
        await self.grant("a")
        for _ in range(2):
            reopened = Db(self.db.path)
            try:
                self.assertFalse(reopened._exec("PRAGMA foreign_key_check").fetchall())
                self.assertIsNotNone(reopened._exec("SELECT id FROM screen_devices WHERE id=?",
                                                  (self.device["id"],)).fetchone())
                self.assertIsNotNone(reopened._exec("SELECT name FROM sqlite_master "
                    "WHERE name='screen_window_device_revoked'").fetchone())
            finally:
                reopened.close()
        # App startup ends grants; the account-paired computer survives.
        register_screen_routes(FastAPI(), self.runtime, self.store)
        self.assertFalse(device_grants(self.db, self.device["id"]))
