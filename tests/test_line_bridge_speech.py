"""An ambassador's bridge message never reaches the chat; only the bridge log shows it."""

import asyncio
import unittest

from partyline.bridge_store import mark_closed
from tests import test_line_bridge as _bridge_tests

Base = _bridge_tests.LineBridgeTest

# The shape of the reported loss: an answer for a person, a bridge message, then a closing mention.
ANSWER = ("Yes, I saw only that one frame.\n\n@[bridge]fable the frame was the only one I got\n\n"
          "@greg")


class BridgeSpeechTest(unittest.TestCase):
    setUp = Base.setUp
    machine = Base.machine
    open = Base.open
    say = Base.say
    rows = Base.rows
    opened = Base.opened

    def test_a_bridge_message_stays_out_of_the_chat_on_both_lines_and_in_the_log(self):
        bridge = self.opened()
        sockets = {"x": _bridge_tests.Socket(), "y": _bridge_tests.Socket()}
        self.runtime.sockets["x"], self.runtime.sockets["y"] = {sockets["x"]}, {sockets["y"]}
        self.assertEqual(self.say("x", "x-amb", ANSWER).status_code, 200)
        for conv in ("x", "y"):
            page = self.client.get(f"/api/conversations/{conv}/messages", headers=self.person)
            self.assertFalse(any(m["body"] == ANSWER for m in page.json()["messages"]), conv)
            self.assertFalse(any(m.get("bridge_id") for m in page.json()["messages"]), conv)
            self.assertEqual([p for p in sockets[conv].sent if p.get("type") == "message"
                              and p["message"]["body"] == ANSWER], [], conv)
        woken = self.adapters["y-amb"].delivered
        self.assertEqual([m["body"] for m in woken], [ANSWER])
        self.assertEqual(woken[0]["audience_attachment_id"], "y-amb")
        for other in ("x-other", "y-other"):
            self.assertEqual(self.adapters[other].delivered, [])
        log = self.client.get(f"/api/bridges/{bridge['id']}/messages", headers=self.person)
        self.assertEqual([m["body"] for m in log.json()], [ANSWER])

    def test_the_log_shows_each_crossing_once_in_order_and_from_both_sides(self):
        bridge = self.opened()
        self.say("x", "x-amb", "@[bridge]fable same words")
        self.say("y", "y-amb", "@[bridge]sonnet same words")
        self.say("x", "x-amb", "@[bridge]fable same words")
        log = self.client.get(f"/api/bridges/{bridge['id']}/messages", headers=self.person).json()
        self.assertEqual([m["conv_id"] for m in log], ["x", "y", "x"])
        self.assertTrue(all(not m.get("audience_attachment_id") for m in log))
        self.assertEqual([m["id"] for m in log], sorted(m["id"] for m in log))

    def test_a_copy_without_its_original_is_kept(self):
        bridge = self.opened()
        self.say("x", "x-amb", "@[bridge]fable only the copy remains")
        original = [r for r in self.rows("x") if r["bridge_id"]][-1]
        self.db._exec("DELETE FROM messages WHERE id=?", (original["id"],))
        log = self.client.get(f"/api/bridges/{bridge['id']}/messages", headers=self.person).json()
        self.assertEqual([(m["conv_id"], m["source_conv_id"]) for m in log], [("y", "x")])

    def test_a_pty_spoken_bridge_message_is_not_fanned_out_to_people(self):
        bridge = self.opened()
        socket = _bridge_tests.Socket()
        self.runtime.sockets["x"] = {socket}
        att = self.db.get_attachment("x-amb")
        post = self.runtime.post_callback("x-amb", "x", att["runtime_owner"])
        asyncio.run(post("sonnet", "agent", "@[bridge]fable via the pty"))
        self.assertEqual(socket.sent, [])
        log = self.client.get(f"/api/bridges/{bridge['id']}/messages", headers=self.person)
        self.assertEqual(len(log.json()), 1)

    def test_a_reaction_on_a_bridge_row_does_not_resurface_it(self):
        self.opened()
        self.say("x", "x-amb", "@[bridge]fable secret plan")
        original = [r for r in self.rows("x") if r["bridge_id"]][-1]
        reacted = self.client.post(f"/api/messages/{original['id']}/reactions",
                                   json={"emoji": "👍"}, headers=self.person)
        self.assertEqual(reacted.status_code, 404)
        page = self.client.get("/api/conversations/x/messages", headers=self.person)
        self.assertFalse(any("secret plan" in m["body"] for m in page.json()["messages"]))

    def test_the_log_stays_readable_after_the_bridge_closes(self):
        bridge = self.opened()
        self.say("x", "x-amb", "@[bridge]fable done")
        mark_closed(self.db, bridge["id"], "greg", "test")
        log = self.client.get(f"/api/bridges/{bridge['id']}/messages", headers=self.person)
        self.assertEqual(len(log.json()), 1)
        page = self.client.get("/api/conversations/x/messages", headers=self.person)
        self.assertFalse(any("done" in m["body"] for m in page.json()["messages"]))

    def test_the_open_notice_points_to_the_bridge_log(self):
        self.opened()
        notices = [r["body"] for r in self.rows("x") if r["sender_type"] == "system"
                   and r["audience_attachment_id"] is None and r["body"].startswith("⇄ bridge opened")]
        self.assertEqual(len(notices), 1)
        self.assertIn("Manage → Bridges → view log", notices[0])

    def test_the_close_notice_does_not_promise_a_log_that_is_gone(self):
        bridge = self.opened()
        mark_closed(self.db, bridge["id"], "greg", "test")
        from partyline.bridge_pack import close_line_notice
        self.assertNotIn("view log", close_line_notice("a", "b", "line", "greg"))
