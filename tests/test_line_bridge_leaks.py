"""Line bridges must never leak bridge text to people or to processes outside the pair."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from partyline.bridge_delivery import bridge_names, speaks_over_bridge
from partyline.captain_docs import reminder_line
from partyline.heartbeat_snapshot import build
from partyline.bridge_store import bridged_across
from partyline.hierarchy import HierarchyError, set_lead, set_parent
from partyline.message_forward import forward_router
from partyline.pin_routes import pin_router
from partyline.reaction_routes import reaction_router
from partyline.reaction_store import message as reaction_message
from partyline.return_path import ReturnPath
from tests import test_line_bridge as _bridge_tests

Base = _bridge_tests.LineBridgeTest


class BridgeLeakTest(unittest.TestCase):
    setUp = Base.setUp
    machine = Base.machine
    open = Base.open
    say = Base.say
    rows = Base.rows
    opened = Base.opened

    def crossed(self):
        self.opened()
        self.say("x", "x-amb", "@[bridge]fable the secret plan")
        return [r for r in self.rows("x") if r["bridge_id"]][-1]

    def test_the_return_notice_never_quotes_bridge_speech_but_counts_as_a_handoff(self):
        self.opened()
        returns = ReturnPath(self.runtime)
        returns.note_spoke("x-amb", "@[bridge]fable the secret plan")
        self.assertNotIn("x-amb", returns.last_said)
        self.assertIn("x-amb", returns.addressed)
        returns.note_spoke("x-amb", "ordinary words to nobody")
        self.assertEqual(returns.last_said["x-amb"], "ordinary words to nobody")

    def test_a_stamped_message_does_not_count_ordinary_mentions_as_handoffs(self):
        self.opened()
        returns = ReturnPath(self.runtime)
        returns.note_spoke("x-amb", "@[bridge]fable psst, tell @gem nothing")
        self.assertEqual(returns.requesters, {})
        self.assertFalse(speaks_over_bridge(self.db, "x-other", "@[bridge]luna hi"))

    def test_by_id_reads_hide_bridge_rows_from_forward_reaction_and_pin(self):
        row = self.crossed()
        self.assertIsNone(self.db.message_by_id("x", row["id"]))
        self.assertIsNone(reaction_message(self.db, row["id"]))
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from partyline.auth_guard import install_auth_guard
        app = FastAPI()
        install_auth_guard(app, self.db)
        for router in (forward_router, reaction_router, pin_router):
            app.include_router(router(self.runtime))
        client = TestClient(app)
        self.addCleanup(client.close)
        forwarded = client.post(f"/api/conversations/x/messages/{row['id']}/forward",
                                json={"to": "kid", "note": ""}, headers=self.person)
        self.assertEqual(forwarded.status_code, 404)
        reacted = client.post(f"/api/messages/{row['id']}/reactions",
                              json={"emoji": "👍"}, headers=self.person)
        self.assertEqual(reacted.status_code, 404)
        pinned = client.post("/api/conversations/x/pins", json={"message_id": row["id"]},
                             headers=self.person)
        self.assertEqual(pinned.status_code, 404)

    def test_a_workers_first_message_is_not_forwarded_to_its_captain_when_it_is_bridge_speech(self):
        self.opened()
        set_lead(self.db, "x", "x-other")
        self.runtime.first_hello_pending.add("x-amb")
        att = self.db.get_attachment("x-amb")
        post = self.runtime.post_callback("x-amb", "x", att["runtime_owner"], route=False)
        with patch("partyline.first_hello.deliver_pending_first_hello", new=AsyncMock()) as hello:
            asyncio.run(post("sonnet", "agent", "@[bridge]fable the secret plan"))
        hello.assert_not_awaited()

    def test_linking_a_line_so_two_bridged_lines_share_a_tree_is_refused(self):
        self.opened()
        self.assertTrue(bridged_across(self.db, "y", "kid"))
        with self.assertRaises(HierarchyError) as caught:
            set_parent(self.db, "y", "kid")
        self.assertEqual(caught.exception.status_code, 409)
        self.db.create_conversation("z", "elsewhere")
        self.assertFalse(bridged_across(self.db, "z", "kid"))

    def test_unread_counts_ignore_bridge_rows(self):
        self.crossed()
        snapshot = build(self.db, "y", 0)
        self.assertEqual([line for line in snapshot["lines"] if line["new"]], [])
        self.assertTrue(all(a["unread"] == 0 for ln in snapshot["lines"] for a in ln["agents"]))
        top = self.db._exec(
            "SELECT MAX(id) m FROM messages WHERE conv_id='y'").fetchone()["m"]
        self.assertEqual(reminder_line(self.db, "y", top - 1)[0], "")

    def test_bridge_speech_in_code_or_with_hidden_characters(self):
        self.assertEqual(bridge_names("`@[bridge]fable` and ```\n@[bridge]luna\n```"), set())
        self.assertEqual(bridge_names("@\u200b[bridge]fable hi"), {"fable"})
        self.opened()
        quoted = self.say("x", "x-amb", "see `@[bridge]fable` in the docs")
        self.assertIsNone(quoted.json().get("bridge_id"))
