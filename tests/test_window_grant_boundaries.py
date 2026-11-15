"""Secret-free picker data, owner isolation and deterministic line-grant races."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.auth_guard import Principal
from partyline.screen_grants import device_grants, resolve_window
from tests.window_grant_fixtures import WindowGrantFixture


class WindowBoundaryTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    def grant_message(self, line="alpha", grant_id="g1"):
        return {"type": "window_grant", "request_id": "grant", "targets_request_id": "targets",
                "line_id": line, "grant_id": grant_id, "title": "Editor", "process": "app", "hwnd": 10}

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
        stored = self.db._exec("SELECT * FROM screen_line_window_grants WHERE id='g1'").fetchone()
        self.assertEqual("alpha", stored["conv_id"])
        self.assertNotIn("runtime_owner", stored.keys())
        self.assertNotIn("attachment_id", stored.keys())

    async def test_a_grant_must_answer_the_current_picker_and_name_an_offered_line(self):
        await self.offer()
        stale = {**self.grant_message(), "targets_request_id": "older"}
        await self.hub.window_grants.from_helper(self.device, stale)
        self.assertFalse(self.sent[-1]["ok"])
        with patch("partyline.screen_window_grants.visible_conversation_ids", return_value={"beta"}):
            await self.offer("narrow")
        narrow = {**self.grant_message(), "targets_request_id": "narrow"}
        await self.hub.window_grants.from_helper(self.device, narrow)
        self.assertFalse(self.sent[-1]["ok"])
        self.assertFalse(device_grants(self.db, self.device["id"]))
        await self.offer()
        await self.hub.window_grants.from_helper(self.device, self.grant_message())
        self.assertTrue(self.sent[-1]["ok"])
        self.assertEqual({"line_id": "alpha", "line_name": "Alpha"}, self.sent[-1]["target"])
        await self.hub.window_grants.from_helper(self.device, self.grant_message(grant_id="g2"))
        self.assertFalse(self.sent[-1]["ok"], "an offer answers once")

    async def test_old_helper_picks_a_process_and_the_server_maps_it_to_its_line(self):
        self.device["windows"] = 0
        await self.offer()
        self.assertEqual({"alpha", "beta"}, {g["line_id"] for g in self.sent[-1]["lines"]})
        legacy = {key: value for key, value in self.grant_message().items() if key != "line_id"}
        await self.hub.window_grants.from_helper(self.device, {**legacy, "attachment_id": "peer"})
        self.assertTrue(self.sent[-1]["ok"])
        self.assertEqual("peer", self.sent[-1]["target"]["name"])
        self.assertEqual("alpha", self.sent[-1]["target"]["line_id"])
        for ident in ("a", "peer"):  # not just the process the old picker named
            self.assertEqual("g1", (await self.read(ident)).json()["window"])
        await self.offer()
        await self.hub.window_grants.from_helper(self.device, {**legacy, "attachment_id": "ended",
                                                               "grant_id": "g2"})
        self.assertFalse(self.sent[-1]["ok"])

    async def test_old_helper_keeps_the_offered_name_when_its_process_is_removed_mid_picker(self):
        self.device["windows"] = 0
        await self.offer()
        self.db._exec("DELETE FROM attachments WHERE id='peer'")  # removed while the picker is open
        legacy = {key: value for key, value in self.grant_message().items() if key != "line_id"}
        await self.hub.window_grants.from_helper(self.device, {**legacy, "attachment_id": "peer"})
        response = self.sent[-1]
        self.assertTrue(response["ok"])
        self.assertEqual({"line_id": "alpha", "line_name": "Alpha", "name": "peer"}, response["target"])
        self.assertEqual("g1", (await self.read("a")).json()["window"])  # the line still holds it

    async def test_helper_that_sends_neither_line_nor_process_is_told_to_update(self):
        await self.offer()
        bare = {key: value for key, value in self.grant_message().items() if key != "line_id"}
        await self.hub.window_grants.from_helper(self.device, bare)
        self.assertFalse(self.sent[-1]["ok"])
        self.assertIn("update the Partyline helper", self.sent[-1]["error"])
        self.device["windows"] = 1  # a current helper never names a process
        await self.offer()
        await self.hub.window_grants.from_helper(self.device, {**bare, "attachment_id": "a"})
        self.assertIn("update the Partyline helper", self.sent[-1]["error"])

    async def test_failed_insert_keeps_old_grant_and_sends_no_revoke(self):
        await self.grant("a")
        self.db._exec("CREATE TRIGGER reject_replacement BEFORE INSERT ON screen_line_window_grants "
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
            changes = [call.args[0] for call in socket.send_json.await_args_list
                       if call.args[0]["type"] == "screen_devices_changed"]
            self.assertEqual([self.device["id"]], [event["device_id"] for event in changes])
        self.assertFalse(any(call.args[0]["type"] == "screen_devices_changed"
                             for call in other.send_json.await_args_list))

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
                "DELETE FROM screen_line_window_grants WHERE id='g1'")):
            response = await self.act("a")
        self.assertEqual(403, response.status_code)
        self.assertFalse(any(m["type"] == "window_element_action" for m in self.sent))
        await self.grant("a", grant_id="g2")
        async def finish_then_end(message):
            await self.receive(message)
            self.db._exec("DELETE FROM screen_line_window_grants WHERE id='g2'")
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
        self.assertEqual(200, (await self.read("peer")).status_code)  # the line's own grant
        self.assertNotIn("private-holder", (await self.read("peer", "nothing")).text)
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
        self.db.add_attachment("foreign", "beta", "private-holder", "raw", ["shell"],
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
        self.assertEqual({"window", "standing"}, {g["kind"] for g in indicators})
        response = await self.client.get(url, headers=self.human(self.other_user))
        self.assertEqual([], response.json()["indicators"])
        self.assertEqual(403, (await self.client.get(url, headers=self.machine("a"))).status_code)
        await self.client.delete("/api/screen/window-grants/g1", headers=self.human(self.owner))
        indicators = (await self.client.get(url, headers=self.human(self.owner))).json()["indicators"]
        self.assertEqual(["beta"], [g["conv_id"] for g in indicators if g["kind"] == "window"])
        self.db.set_attachment_status("b", "exited", "activation-b")  # the line keeps its grant
        response = await self.client.get(url, headers=self.human(self.owner))
        self.assertEqual(["beta"], [g["conv_id"] for g in response.json()["indicators"]
                                   if g["kind"] == "window"])

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
                    "WHERE name='screen_line_window_device_revoked'").fetchone())
                self.assertFalse(reopened._exec("SELECT name FROM sqlite_master WHERE name IN "
                    "('screen_window_attachment_ended','screen_window_attachment_deleted',"
                    "'screen_window_grants')").fetchall())
            finally:
                reopened.close()
        # App startup ends grants; the account-paired computer survives.
        register_screen_routes(FastAPI(), self.runtime, self.store)
        self.assertFalse(device_grants(self.db, self.device["id"]))

    async def test_a_refusal_never_names_or_confirms_a_line_the_caller_cannot_see(self):
        await self.grant("a", "Secret plans", "hidden")
        self.db.create_conversation("quiet", "Quiet")
        self.db.add_attachment("q", "quiet", "q", "raw", ["shell"], "/tmp", "activation-q")
        self.db.set_attachment_status("q", "running", "activation-q")
        missing = (await self.read("q", "nothing-like-it")).text
        for window in (None, "hidden", "Secret plans"):
            for call in (self.read, self.act):
                response = await call("q", window)
                self.assertEqual(403, response.status_code)
                self.assertNotIn("Alpha", response.text)
                self.assertNotIn("Secret plans", response.text)
                self.assertNotIn("hidden", response.text)
        self.assertEqual(missing, (await self.read("q", "hidden")).text)
        self.assertEqual(missing, (await self.read("q", "Secret plans")).text)
        response = await self.client.post("/api/conversations/quiet/screen-elements",
            params={"device": "Computer", "window": "hidden"}, headers=self.machine("q"))
        self.assertEqual(missing, response.text)

    async def test_a_captain_is_told_which_visible_subline_holds_the_window(self):
        await self.grant("a")
        self.db._exec("UPDATE conversations SET parent_id='paired' WHERE id='alpha'")
        self.db.add_attachment("boss", "paired", "boss", "raw", ["shell"], "/tmp", "activation-boss")
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='boss'")
        for window in (None, "g1", "Editor"):
            response = await self.read("boss", window)
            self.assertEqual(403, response.status_code)
            self.assertIn("held by line «Alpha»", response.text)
        response = await self.read("b", "g1")  # a sibling cannot see it
        self.assertNotIn("Alpha", response.text)

    async def test_an_old_per_process_database_upgrades_and_reopens_without_grants(self):
        from partyline.db import Db
        from partyline.screen_grant_schema import MIGRATIONS as OLD

        await self.grant("a")
        for name in ("screen_line_window_device_revoked", "screen_line_window_line_archived"):
            self.db._exec("DROP TRIGGER " + name)
        self.db._exec("DROP TABLE screen_line_window_grants")
        for statement in OLD:  # the schema a shipped database has, with a live row in it
            self.db._exec(statement)
        self.db._exec(
            "INSERT INTO screen_window_grants(id,device_id,attachment_id,runtime_owner,title,process,hwnd) "
            "VALUES('old',?,'a','activation-a','Editor','app',1)", (self.device["id"],))
        for _ in range(3):  # repeated opens are safe
            reopened = Db(self.db.path)
            try:
                names = {row["name"] for row in reopened._exec("SELECT name FROM sqlite_master").fetchall()}
                self.assertIn("screen_line_window_grants", names)
                self.assertTrue({"screen_line_window_device_revoked",
                                 "screen_line_window_line_archived"} <= names)
                self.assertFalse({"screen_window_grants", "screen_window_attachment_ended",
                                  "screen_window_attachment_deleted", "screen_window_device_revoked"} & names)
                self.assertEqual([], reopened._exec("SELECT id FROM screen_line_window_grants").fetchall())
                self.assertFalse(reopened._exec("PRAGMA foreign_key_check").fetchall())
            finally:
                reopened.close()
