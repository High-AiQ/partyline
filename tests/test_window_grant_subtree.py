"""Downward window inheritance in a person-built line tree, without captains or tasks."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.auth_guard import Principal
from partyline.machine_scope import allows, visible_conversation_ids
from partyline.screen_capabilities import for_attachment
from partyline.screen_grants import device_grants
from partyline.screen_share_notices import _window_share_on_line
from partyline.screen_window_notices import line_window_text
from tests.window_grant_fixtures import WindowGrantFixture


class WindowSubtreeTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for line, parent in (("child", "alpha"), ("grandchild", "child"), ("sibling", "alpha")):
            self.db.create_conversation(line, line.title(), captain_mode="off")
            self.db._exec("UPDATE conversations SET parent_id=? WHERE id=?", (parent, line))
            self.db.add_attachment(line, line, line, "raw", ["shell"], "/tmp", "activation-" + line)
        for ident in ("a", "peer", "child", "grandchild", "sibling"):
            self.db.set_attachment_status(ident, "running", "activation-" + ident)
            self.runtime.live[ident] = SimpleNamespace(
                att=self.db.get_attachment(ident), deliver=AsyncMock(return_value=True))

    def principal(self, ident):
        return Principal(kind="machine", name=ident, attachment_id=ident,
                         conv_id=self.db.get_attachment(ident)["conv_id"])

    def notices(self, ident):
        return [message for call in self.runtime.live[ident].deliver.call_args_list
                for message in call.args[0] if message.get("audience_attachment_id") == ident]

    async def test_root_grant_serves_child_and_grandchild_with_shared_snapshot(self):
        offered = {line["line_id"]: line for line in (await self.offer())["lines"]}
        self.assertEqual("alpha", offered["child"]["parent_id"])
        self.assertEqual("child", offered["grandchild"]["parent_id"])
        await self.grant("a")
        for ident in ("a", "child", "grandchild"):
            for window in (None, "g1", "Editor"):
                response = await self.read(ident, window)
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual("g1", response.json()["window"])
                if ident != "a":
                    self.assertEqual("Alpha", response.json()["inherited_from"])
                else:
                    self.assertNotIn("inherited_from", response.json())
            self.assertFalse(self.db.get_attachment(ident)["is_lead"])
        self.assertEqual(1, sum(m["type"] == "read_window_elements" for m in self.sent))
        for ident in ("a", "child", "grandchild"):
            self.assertEqual(200, (await self.act(ident)).status_code)

    async def test_child_grant_is_refused_to_parent_sibling_and_unrelated_line(self):
        await self.grant("child")
        self.assertEqual(200, (await self.read("grandchild")).status_code)
        for ident in ("a", "sibling", "b"):
            for window in (None, "g1", "Editor"):
                for call in (self.read, self.act):
                    response = await call(ident, window)
                    self.assertEqual(403, response.status_code)
                    self.assertIn("no window is shared with this line", response.text)
                    self.assertNotIn("«Child»", response.text)
        # A captain may learn which descendant holds it, but cannot use it upwards.
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='a'")
        response = await self.read("a", "g1")
        self.assertEqual(403, response.status_code)
        self.assertIn("«Child»", response.text)

    async def test_several_windows_across_ancestry_list_lines_and_exact_selection(self):
        for ident, title, grant, hwnd in (("a", "Editor", "g1", 10),
                                          ("child", "Browser", "g2", 20),
                                          ("grandchild", "Terminal", "g3", 30)):
            await self.grant(ident, title, grant, hwnd)
        for call in (self.read, self.act):
            response = await call("grandchild")
            self.assertEqual(409, response.status_code)
            for line in ("Alpha", "Child", "Grandchild"):
                self.assertIn("«" + line + "»", response.text)
            for window in ("g1", "Editor", "g2", "Browser", "g3", "Terminal"):
                self.assertEqual(200, (await call("grandchild", window)).status_code)
        # An exact id beats a title collision, regardless of where the grant lives.
        await self.grant("grandchild", "g1", "g4", 40)
        self.assertEqual("g1", (await self.read("grandchild", "g1")).json()["window"])

    async def test_notices_reach_live_descendants_privately_and_revoke_them_once(self):
        self.db.archive_conversation("sibling")
        self.db.add_attachment("stopped", "child", "stopped", "raw", ["shell"], "/tmp", "act-s")
        self.db.set_attachment_status("stopped", "exited", "act-s")
        await self.grant("a")
        self.assertEqual(1, len(self.db.list_messages("alpha")))
        for ident in ("child", "grandchild"):
            notice, = self.notices(ident)
            self.assertIn("shared", notice["body"])
            self.assertIn("«Alpha»", notice["body"])
            self.assertIn("inherited and usable from this subline", notice["body"])
            self.assertIn('screen_elements(window="g1")', notice["body"])
            self.assertEqual([], self.db.list_messages(ident))
        self.assertEqual([], self.notices("sibling"))
        self.assertEqual([], self.db.messages_after("child", 0, "stopped", "stopped"))
        await self.hub.window_grants.revoke("g1")
        await self.hub.window_grants.revoke("g1")
        for ident in ("child", "grandchild"):
            self.assertEqual(2, len(self.notices(ident)))
            self.assertIn("no longer shared", self.notices(ident)[-1]["body"])
            self.assertIn("inherited from «Alpha»", self.notices(ident)[-1]["body"])
            self.assertEqual([], self.db.list_messages(ident))

    async def test_attach_and_rebrief_include_inherited_grants(self):
        from partyline.rebrief import render_rebrief
        from partyline.role_delivery import bind_role_delivery

        await self.grant("a")
        self.db.add_attachment("late", "grandchild", "late", "raw", ["shell"], "/tmp", "act-late")
        late = self.db.get_attachment("late")
        late["digest_rider"] = lambda: ""
        bind_role_delivery(self.db, late)
        for text in (late["role_briefing"], render_rebrief(self.db, late)):
            for expected in ('window="g1"', "inherited from «Alpha»", "screen_elements", "Editor"):
                self.assertIn(expected, text)
        # Inherited grants name their line through the grant row, not through general visibility.
        self.assertEqual({"grandchild"},
                         visible_conversation_ids(self.db, self.principal("grandchild")))
        self.assertFalse(allows(self.db, self.principal("grandchild"), "alpha", "read"))
        self.assertEqual("", line_window_text(self.db, "beta"))

    async def test_tools_capabilities_and_share_notice_use_inherited_grants(self):
        principal = self.principal("grandchild")
        self.assertFalse(for_attachment(self.runtime, principal, "grandchild", {})["screen_windows"])
        await self.grant("a")
        self.assertTrue(for_attachment(self.runtime, principal, "grandchild", {})["screen_windows"])
        self.assertTrue(_window_share_on_line(self.hub, "grandchild"))
        await self.hub.window_grants.revoke("g1")
        self.assertFalse(for_attachment(self.runtime, principal, "grandchild", {})["screen_windows"])

    async def test_archiving_subline_keeps_parent_grant_and_blocks_its_branch(self):
        from partyline.line_subtree import archive_line

        await self.grant("a")
        with patch("partyline.line_subtree.close_for_line", new_callable=AsyncMock), \
                patch("partyline.line_subtree.docker_relay.stop", new_callable=AsyncMock):
            await archive_line(self.runtime, "child")
        self.assertEqual(["g1"], [g["id"] for g in device_grants(self.db, self.device["id"])])
        self.assertEqual(200, (await self.read("a")).status_code)
        self.assertEqual(200, (await self.read("sibling")).status_code)
        for ident in ("child", "grandchild"):
            self.assertIn((await self.read(ident)).status_code, (401, 403))
            self.assertEqual("", line_window_text(self.db, ident))
        self.assertNotIn({"type": "revoke_window", "grant_id": "g1"}, self.sent)

    async def test_archiving_owner_ends_inherited_access(self):
        await self.grant("a")
        self.db.archive_conversation("alpha")
        await self.hub.window_grants.expire()
        self.assertEqual([], device_grants(self.db, self.device["id"]))
        for ident in ("a", "child", "grandchild"):
            self.assertEqual(403, (await self.read(ident)).status_code)
        self.assertIn({"type": "revoke_window", "grant_id": "g1"}, self.sent)
