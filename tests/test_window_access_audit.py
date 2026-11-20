"""Standing window calls stay in their verifiable log, not in chat."""
import unittest
from unittest.mock import patch

from partyline.notice_policy import digest_candidates
from partyline.screen_audit import record, record_window_access
from partyline.screen_standing import update_mirror
from tests.window_grant_fixtures import WindowGrantFixture


class WindowAccessAuditTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def test_calls_keep_rows_and_chain_but_post_only_first_use(self):
        with patch("partyline.screen_audit.time") as clock:
            clock.time.side_effect = (10.0, 11.0, 12.0)
            for index in range(3):
                await record_window_access(self.runtime, "alpha", "worker", "uia_read",
                                           "editor.exe", "Catalog", f"read {index}", self.device)
        rows = self.db._exec("SELECT * FROM screen_control_audit ORDER BY id").fetchall()
        self.assertEqual(3, len(rows))
        self.assertTrue(all(row["message_id"] is None for row in rows))
        self.assertEqual([10.0, 11.0, 12.0], [row["created_at"] for row in rows])
        self.assertEqual("", rows[0]["previous_hash"])
        self.assertEqual(rows[0]["entry_hash"], rows[1]["previous_hash"])
        self.assertEqual(rows[1]["entry_hash"], rows[2]["previous_hash"])
        messages = self.db.list_messages("alpha")
        self.assertEqual(1, len(messages))
        self.assertEqual("Agents on this line are using window access on Computer; "
                         "log: Settings → Computers", messages[0]["body"])

        other = {**self.device, "id": "other-device", "name": "Laptop"}
        await record_window_access(self.runtime, "alpha", "worker", "list", "windows",
                                   "window list", "listed 1", other)
        self.assertEqual(2, len(self.db.list_messages("alpha")))

    async def test_notice_returns_after_access_is_revoked_and_regranted(self):
        await record_window_access(self.runtime, "alpha", "worker", "list", "windows",
                                   "window list", "listed 1", self.device)
        await record_window_access(self.runtime, "alpha", "worker", "list", "windows",
                                   "window list", "listed 1", self.device)
        self.assertEqual(1, len(self.db.list_messages("alpha")))
        await update_mirror(self.hub, self.device, {"type": "window_access_changed", "enabled": False})
        await update_mirror(self.hub, self.device, {"type": "window_access_changed", "enabled": True})
        await record_window_access(self.runtime, "alpha", "worker", "list", "windows",
                                   "window list", "listed 1", self.device)
        self.assertEqual(2, len(self.db.list_messages("alpha")))

    async def test_restart_keeps_pending_and_published_entries_in_the_log_only(self):
        record(self.db, "share-1", "alpha", "worker", "type `private` (7 chars) (interrupted: private)")
        published = self.db.add_message("alpha", "system", "system", "Agent control audit — legacy")
        self.db._exec("UPDATE screen_control_audit SET message_id=?", (published["id"],))
        record(self.db, "share-1", "alpha", "peer", "click left (1,2)")
        record(self.db, "share-1", "beta", "b", "move (3,4)")
        record(self.db, "window-access:alpha", "alpha", "worker", "list: windows — window list (listed 1)")
        notice = self.db.add_message("alpha", "system", "system", "@a Agent control was not granted.")
        similar = self.db.add_message("alpha", "system", "system", "Agent control audit — status changed")
        rows = self.db._exec("SELECT * FROM screen_control_audit ORDER BY id").fetchall()

        await self.restart_server()
        self.assertEqual(rows, self.db._exec("SELECT * FROM screen_control_audit ORDER BY id").fetchall())
        self.assertEqual(3, self.db._exec("SELECT count(*) FROM messages").fetchone()[0])
        visible = [notice["id"], similar["id"]]
        for history in (self.db.list_messages("alpha"), self.db.message_page("alpha", after_id=0)[0],
                        digest_candidates(self.db, "alpha", 0, "a", "a"),
                        self.db.messages_by_ids("alpha", [published["id"], *visible])):
            self.assertEqual(visible, [message["id"] for message in history])
        self.assertIsNone(self.db.message_by_id("alpha", published["id"]))

        path = "/api/conversations/alpha/screen-access-audit"
        for credential in (self.machine("a"), self.machine("b")):
            self.assertEqual(403, (await self.client.get(path, headers=credential)).status_code)
        headers = self.human(self.other_user)
        first = (await self.client.get(path, params={"limit": 2}, headers=headers)).json()
        self.assertEqual(["window-access:alpha", "share-1"], [row["chain_id"] for row in first["entries"]])
        self.assertEqual(["worker", "peer"], [row["agent"] for row in first["entries"]])
        older = (await self.client.get(path, params={"before": first["next_before"]}, headers=headers)).json()
        self.assertIsNone(older["next_before"])
        self.assertEqual(1, len(older["entries"]))
        typed = older["entries"][0]
        self.assertEqual("type (7 chars) (interrupted)", typed["detail"])
        self.assertEqual(rows[0]["entry_hash"], typed["entry_hash"])
        self.assertEqual(typed["entry_hash"], first["entries"][1]["previous_hash"])
        beta = await self.client.get("/api/conversations/beta/screen-access-audit", headers=headers)
        self.assertEqual(["move (3,4)"], [row["detail"] for row in beta.json()["entries"]])

    async def test_person_route_auth_order_limit_fields_and_chain_head(self):
        with patch("partyline.screen_audit.time") as clock:
            clock.time.side_effect = (1.0, 2.0, 3.0, 4.0)
            for index in range(4):
                await record_window_access(self.runtime, "alpha", "worker", "uia_read",
                                           "editor.exe", f"Catalog {index}", f"read {index}")
        path = "/api/conversations/alpha/window-access-audit"
        for credential in (self.machine("a"), self.machine("b")):
            response = await self.client.get(path, headers=credential)
            self.assertEqual(403, response.status_code)
        response = await self.client.get(path + "?limit=2", headers=self.human(self.owner))
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual([3, 2], [int(row["title"].rsplit(" ", 1)[1]) for row in payload["entries"]])
        self.assertEqual({"agent", "call", "app", "title", "result", "time", "entry_hash"},
                         set(payload["entries"][0]))
        self.assertEqual({"agent": "worker", "call": "uia_read", "app": "editor.exe",
                          "title": "Catalog 3", "result": "read 3", "time": 4.0},
                         {key: value for key, value in payload["entries"][0].items() if key != "entry_hash"})
        head = self.db._exec(
            "SELECT entry_hash FROM screen_control_audit ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(head["entry_hash"], payload["chain_head"])
        other = await self.client.get(path, headers=self.human(self.other_user))
        self.assertEqual(4, len(other.json()["entries"]))
        invalid = await self.client.get(path + "?limit=0", headers=self.human(self.owner))
        self.assertEqual(422, invalid.status_code)
        self.assertEqual(404, (await self.client.get(
            "/api/conversations/missing/window-access-audit", headers=self.human(self.owner))).status_code)
