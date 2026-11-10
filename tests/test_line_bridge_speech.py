"""An ambassador's bridge message is said on its own line, and only its copy stays off the chat."""

import unittest

from partyline.bridge_store import mark_closed
from partyline.message_queries import select_message_by_id
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

    def test_an_answer_with_a_bridge_message_stays_in_the_chat_and_the_peer_gets_the_copy(self):
        self.opened()
        self.assertEqual(self.say("x", "x-amb", ANSWER).status_code, 200)
        page = self.client.get("/api/conversations/x/messages", headers=self.person)
        shown = [m for m in page.json()["messages"] if m["body"] == ANSWER]
        self.assertEqual(len(shown), 1)
        self.assertIsNotNone(shown[0]["bridge_id"])
        self.assertEqual(shown[0]["bridge_peer_conv_name"], "tool")
        woken = self.adapters["y-amb"].delivered
        self.assertEqual([m["body"] for m in woken], [ANSWER])
        self.assertEqual(woken[0]["audience_attachment_id"], "y-amb")
        for other in ("x-other", "y-other"):
            self.assertEqual(self.adapters[other].delivered, [])
        peer_page = self.client.get("/api/conversations/y/messages", headers=self.person)
        self.assertFalse(any(m["body"] == ANSWER for m in peer_page.json()["messages"]))

    def test_the_peer_name_on_the_tag_survives_the_bridge_closing(self):
        bridge = self.opened()
        self.say("x", "x-amb", "@[bridge]fable done")
        mark_closed(self.db, bridge["id"], "greg", "test")
        page = self.client.get("/api/conversations/x/messages", headers=self.person)
        tagged = [m for m in page.json()["messages"] if m["body"] == "@[bridge]fable done"]
        self.assertEqual(tagged[0]["bridge_peer_conv_name"], "tool")

    def test_the_counterpart_copy_names_the_line_it_came_from(self):
        self.opened()
        self.say("x", "x-amb", "@[bridge]fable hi")
        copy = [r for r in self.rows("y") if r["bridge_id"]][-1]
        self.assertEqual(self.db.message_by_id("y", copy["id"]), None)
        raw = select_message_by_id(self.db._exec, "y", copy["id"])
        self.assertEqual(raw["bridge_peer_conv_name"], "3d game")
