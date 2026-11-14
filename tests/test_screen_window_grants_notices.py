"""Window lifecycle notices use the real private-message routing and digest filters."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from partyline.screen_grants import device_grants
from partyline.screen_window_notices import line_window_text
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

    async def test_grant_is_delivered_once_to_every_process_on_the_line_without_secrets(self):
        await self.grant("a", "Chrome\nA tab @peer")
        await self.grant("a", "Chrome\nA tab @peer")  # duplicate cannot notify again
        await self.hub.window_grants.expire()
        await self.hub.window_grants.changed(self.device["id"])
        first, = self.notices("a")
        second, = self.notices("peer")
        for notice in (first, second):
            for expected in ("granted", "Chrome A tab @peer", "g1", "Computer", "owner", "this line"):
                self.assertIn(expected, notice["body"])
            notice_text = notice["body"].splitlines()[-1]
            self.assertIn('screen_elements(window="g1")', first["body"])
            self.assertIn("summary", first["body"])
            self.assertIn("find, ls, or text", first["body"])
            self.assertIn("screen_element_action", first["body"])
            self.assertIn("refresh", first["body"])
            self.assertIn("Every process on this line", notice["body"])
            self.assertTrue(notice_text)
        self.runtime.live["b"].deliver.assert_not_awaited()
        for ident in ("a", "b", "peer"):
            pending = self.db.messages_after(self.db.get_attachment(ident)["conv_id"], 0, ident, ident)
            private = sum(bool(m["audience_attachment_id"]) for m in pending)
            self.assertEqual(0 if ident == "b" else 1, private)
        serialized = json.dumps([first, second])
        self.assertNotIn("runtime_owner", serialized)
        self.assertNotIn("activation-", serialized)
        visible = self.db.list_messages("alpha")
        self.assertEqual(["🪟 owner shared «Chrome A tab @peer» with this line"],
                         [m["body"] for m in visible])
        self.assertEqual("system", visible[0]["sender_type"])
        self.assertEqual([], self.db.list_messages("beta"))

    async def test_a_plain_line_with_one_person_attached_process_is_told(self):
        self.db.create_conversation("plain", "Plain", captain_mode="off")
        self.db.add_attachment("solo", "plain", "solo", "raw", ["shell"], "/tmp", "activation-solo")
        self.db.set_attachment_status("solo", "running", "activation-solo")
        self.runtime.live["solo"] = SimpleNamespace(att=self.db.get_attachment("solo"),
                                                    deliver=AsyncMock(return_value=True))
        await self.grant("solo")
        self.assertEqual(1, len(self.notices("solo")))
        self.assertEqual(200, (await self.read("solo")).status_code)

    async def test_replacement_tells_the_old_line_then_grants_the_new_line(self):
        await self.grant("a")
        await self.grant("b", grant_id="g2")
        await self.helper_end(grant_id="g1")  # stale helper acknowledgement
        for ident in ("a", "peer"):
            old = self.notices(ident)
            self.assertEqual(2, len(old))
            self.assertIn("no longer shared with this line: replaced by another grant", old[-1]["body"])
        new, = self.notices("b")
        self.assertIn("granted", new["body"])
        self.assertIn('window="g2"', new["body"])
        self.assertLess(self.notices("a")[-1]["id"], new["id"])
        self.assertEqual(["🪟 owner shared «Editor» with this line"],
                         [m["body"] for m in self.db.list_messages("beta")])
        self.assertEqual(2, len(self.db.list_messages("alpha")))

    async def test_web_revoke_close_and_disconnect_each_notify_once(self):
        ending_seen = [0]
        for ending in ("web", "device", "revoked by the person", "window closed", "helper disconnected"):
            with self.subTest(ending=ending):
                await self.grant("a")
                before, peer_before = len(self.notices("a")), len(self.notices("peer"))
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
                self.assertEqual(1, len(self.notices("peer")) - peer_before)
                self.assertEqual(1, len(notices))
                self.assertIn("no longer shared", notices[0]["body"])
                self.assertIn("revoked by the person" if ending in ("web", "device") else ending,
                              notices[0]["body"])
                self.assertEqual(1, len(notices[0]["body"].splitlines()))
                ended = sum("no longer shared" in m["body"] for m in self.db.list_messages("alpha"))
                self.assertEqual(1, ended - ending_seen[0])
                ending_seen[0] += 1
                if ending == "device":
                    self.db._exec("UPDATE screen_devices SET revoked_at=NULL WHERE id=?",
                                  (self.device["id"],))
                    self.hub.devices[self.device["id"]] = self.device

    async def test_detach_exit_rotation_and_deletion_of_a_process_do_not_end_the_grant(self):
        await self.grant("a")
        for status in ("detached", "exited", "reactivated", "deleted"):
            with self.subTest(status=status):
                if status == "reactivated":
                    self.db._exec("UPDATE attachments SET runtime_owner='new-secret' WHERE id='a'")
                elif status == "deleted":
                    self.db._exec("DELETE FROM attachments WHERE id='a'")
                else:
                    self.db.set_attachment_status("a", status, "activation-a")
                await self.hub.window_grants.expire()
                self.assertIn("g1", self.hub.window_grants.known)
                self.assertEqual(["g1"], [g["id"] for g in device_grants(self.db, self.device["id"])])
                self.assertEqual(1, len(self.notices("peer")))  # nothing new
                self.assertNotIn({"type": "revoke_window", "grant_id": "g1"}, self.sent)
                self.assertEqual(200, (await self.read("peer")).status_code)

    async def test_archiving_the_line_ends_the_grant_without_noise_on_the_archived_line(self):
        await self.grant("a")
        before = len(self.db.list_messages("alpha"))
        self.db.archive_conversation("alpha")
        await self.hub.window_grants.expire()
        self.assertEqual([], device_grants(self.db, self.device["id"]))
        self.assertIn({"type": "revoke_window", "grant_id": "g1"}, self.sent)
        self.assertEqual(before, len(self.db.list_messages("alpha")))
        self.assertEqual(1, len(self.notices("peer")))

    async def test_a_process_that_attaches_later_learns_of_live_grants_in_its_briefing(self):
        from partyline.rebrief import render_rebrief
        from partyline.role_delivery import bind_role_delivery

        self.assertEqual("", line_window_text(self.db, "alpha"))
        await self.grant("a", "Chrome tab")
        self.db.add_attachment("late", "alpha", "late", "raw", ["shell"], "/tmp", "activation-late")
        late = self.db.get_attachment("late")
        late["digest_rider"] = lambda: ""
        bind_role_delivery(self.db, late)
        for text in (late["role_briefing"], render_rebrief(self.db, late)):
            self.assertIn("«Chrome tab»", text)
            self.assertIn('window="g1"', text)
            self.assertIn("Computer", text)
            self.assertIn("any process here", text)
        self.assertEqual("", line_window_text(self.db, "beta"))
        self.assertEqual("", line_window_text(object(), "alpha"))

    async def test_failed_replacement_preserves_grant_and_sends_no_notices(self):
        await self.grant("a")
        self.db._exec("CREATE TRIGGER reject_notice_replacement BEFORE INSERT ON screen_line_window_grants "
                      "WHEN NEW.id='g2' BEGIN SELECT RAISE(ABORT,'failed insert'); END")
        self.assertFalse((await self.grant("b", grant_id="g2"))["ok"])
        self.assertEqual(1, len(self.notices("a")))
        self.assertEqual([], self.notices("b"))

    async def test_helper_receives_success_before_a_process_is_notified(self):
        async def deliver(messages):
            self.assertTrue(self.sent[-1]["ok"])
            self.assertEqual("window_grant_result", self.sent[-1]["type"])
            return True
        self.runtime.live["a"].deliver.side_effect = deliver
        await self.grant("a")
        self.assertEqual(1, len(self.notices("a")))

    async def test_window_change_invalidates_only_a_grant_from_its_device(self):
        await self.grant("a")
        changed = Mock()
        self.hub.elements.changed = changed
        await self.hub.window_grants.from_helper(self.device,
            {"type": "window_changed", "grant_id": "g1"})
        changed.assert_called_once_with("g1")
        changed.reset_mock()
        await self.hub.window_grants.from_helper({**self.device, "id": "another"},
            {"type": "window_changed", "grant_id": "g1"})
        changed.assert_not_called()
