"""Standing window calls stay in their verifiable log, not in chat."""
import unittest
from unittest.mock import patch

from partyline.screen_audit import publish, record, record_window_access, recover
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

    async def test_recovery_never_publishes_window_rows_and_pixel_audit_is_unchanged(self):
        record(self.db, "window-access:alpha", "alpha", "worker", "list: windows — window list (listed 1)")
        record(self.db, "share-1", "alpha", "worker", "click left (1,2)")
        self.assertIsNone(publish(self.db, "window-access:alpha"))
        recover(self.db)
        recover(self.db)
        messages = self.db.list_messages("alpha")
        self.assertEqual(1, len(messages))
        self.assertTrue(messages[0]["body"].startswith("Agent control audit — worker: click left (1,2)"))
        rows = self.db._exec("SELECT share_id,message_id FROM screen_control_audit ORDER BY id").fetchall()
        self.assertIsNone(rows[0]["message_id"])
        self.assertIsNotNone(rows[1]["message_id"])

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
