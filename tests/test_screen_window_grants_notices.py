"""Window lifecycle notices use the real private-message routing and digest filters."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.window_grant_fixtures import WindowGrantFixture


class WindowNoticeTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for ident in ("a", "b", "peer"):
            self.db.set_attachment_status(ident, "running", "activation-" + ident)
            self.runtime.live[ident] = SimpleNamespace(
                att=self.db.get_attachment(ident), deliver=AsyncMock(return_value=True))

    def notices(self, ident):
        return [message for call in self.runtime.live[ident].deliver.call_args_list
                for message in call.args[0] if message.get("audience_attachment_id") == ident]

    async def helper_end(self, reason=None, grant_id="g1"):
        await self.hub.window_grants.from_helper(self.device, {
            "type": "window_revoked", "grant_id": grant_id,
            **({"reason": reason} if reason else {})})

    async def test_grant_is_delivered_once_only_to_target_without_secrets(self):
        await self.grant("a", "Chrome\nA tab @peer")
        await self.grant("a", "Chrome\nA tab @peer")  # duplicate cannot notify again
        await self.hub.window_grants.expire()
        await self.hub.window_grants.changed(self.device["id"])
        notice, = self.notices("a")
        for expected in ("granted", "Chrome A tab @peer", "g1", "Computer", "owner"):
            self.assertIn(expected, notice["body"])
        self.assertEqual('screen_elements(window="g1") to read; screen_element_action to act.',
                         notice["body"].splitlines()[-1])
        self.runtime.live["b"].deliver.assert_not_awaited()
        self.runtime.live["peer"].deliver.assert_not_awaited()
        for ident in ("a", "b", "peer"):
            pending = self.db.messages_after(self.db.get_attachment(ident)["conv_id"], 0, ident, ident)
            self.assertEqual(1 if ident == "a" else 0,
                             sum(bool(m["audience_attachment_id"]) for m in pending))
        serialized = json.dumps(notice)
        self.assertNotIn("runtime_owner", serialized)
        self.assertNotIn("activation-", serialized)
        visible = self.db.list_messages("alpha")
        self.assertEqual(["🪟 owner shared «Chrome A tab @peer» with @a"], [m["body"] for m in visible])
        self.assertEqual("system", visible[0]["sender_type"])
        self.assertEqual([], self.db.list_messages("beta"))

    async def test_replacement_tells_old_holder_then_grants_new_holder(self):
        await self.grant("a")
        await self.grant("b", grant_id="g2")
        await self.helper_end(grant_id="g1")  # stale helper acknowledgement
        old = self.notices("a")
        self.assertEqual(2, len(old))
        self.assertIn("no longer shared: replaced by another grant", old[-1]["body"])
        new, = self.notices("b")
        self.assertIn("granted", new["body"])
        self.assertIn('window="g2"', new["body"])
        self.assertLess(old[-1]["id"], new["id"])
        self.assertEqual(["🪟 owner shared «Editor» with @b"],
                         [m["body"] for m in self.db.list_messages("beta")])

    async def test_web_revoke_close_and_disconnect_each_notify_once(self):
        for ending in ("web", "device", "revoked by the person", "window closed", "helper disconnected"):
            with self.subTest(ending=ending):
                await self.grant("a")
                before = len(self.notices("a"))
                if ending in ("web", "device"):
                    url = ("/api/screen/window-grants/g1" if ending == "web" else
                           f"/api/screen/devices/{self.device['id']}")
                    # Revoking a computer deletes its rows by trigger before cleanup runs.
                    if ending == "device":
                        self.device["socket"].close = AsyncMock()
                    response = await self.client.delete(url,
                                                       headers=self.human(self.owner))
                    self.assertEqual(200, response.status_code)
                elif ending == "helper disconnected":
                    await self.hub.window_grants.disconnected(self.device["id"])
                    await self.hub.window_grants.disconnected(self.device["id"])
                else:
                    await self.helper_end(None if ending == "revoked by the person" else ending)
                await self.helper_end()
                await self.hub.window_grants.expire()
                notices = self.notices("a")[before:]
                self.assertEqual(1, len(notices))
                self.assertIn("no longer shared", notices[0]["body"])
                self.assertIn("revoked by the person" if ending in ("web", "device") else ending,
                              notices[0]["body"])
                self.assertEqual(1, len(notices[0]["body"].splitlines()))
                if ending == "device":
                    self.db._exec("UPDATE screen_devices SET revoked_at=NULL WHERE id=?",
                                  (self.device["id"],))
                    self.hub.devices[self.device["id"]] = self.device
        self.runtime.live["peer"].deliver.assert_not_awaited()

    async def test_detach_exit_and_reactivation_do_not_receive_end_notices(self):
        for status in ("detached", "exited", "reactivated", "deleted"):
            with self.subTest(status=status):
                await self.grant("a")
                before = self.runtime.live["a"].deliver.await_count
                if status == "reactivated":
                    self.db._exec("UPDATE attachments SET runtime_owner='new-secret' WHERE id='a'")
                elif status == "deleted":
                    self.db._exec("DELETE FROM attachments WHERE id='a'")
                else:
                    self.db.set_attachment_status("a", status, "activation-a")
                await self.hub.window_grants.expire()
                await self.hub.window_grants.disconnected(self.device["id"])
                self.assertEqual(before, self.runtime.live["a"].deliver.await_count)
                if status != "deleted":
                    self.db._exec("UPDATE attachments SET status='running',runtime_owner='activation-a' "
                                  "WHERE id='a'")

    async def test_failed_replacement_preserves_grant_and_sends_no_notices(self):
        await self.grant("a")
        self.db._exec("CREATE TRIGGER reject_notice_replacement BEFORE INSERT ON screen_window_grants "
                      "WHEN NEW.id='g2' BEGIN SELECT RAISE(ABORT,'failed insert'); END")
        self.assertFalse((await self.grant("b", grant_id="g2"))["ok"])
        self.assertEqual(1, len(self.notices("a")))
        self.assertEqual([], self.notices("b"))

    async def test_helper_receives_success_before_process_is_notified(self):
        async def deliver(messages):
            self.assertTrue(self.sent[-1]["ok"])
            self.assertEqual("window_grant_result", self.sent[-1]["type"])
            return True
        self.runtime.live["a"].deliver.side_effect = deliver
        await self.grant("a")
        self.assertEqual(1, len(self.notices("a")))
