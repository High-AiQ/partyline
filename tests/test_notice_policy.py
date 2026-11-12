"""Only notices a process must act on are pasted into it; people still read all of them."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from partyline.db import Db
from partyline.message_visibility import is_reaction_notice
from partyline.notice_policy import classify, digest_candidates
from partyline.resume_backlog import addressed_backlog

HOUR = json.loads((Path(__file__).parent / "fixtures" / "notice_hour.json").read_text())


class NoticePolicyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "x.db"))
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "line")
        self.db.add_attachment("me", "line", HOUR["agent"], "fake", ["run"], "/tmp")
        self.db.add_attachment("other", "line", "someone", "fake", ["run"], "/tmp")

    def post(self, event):
        message = self.db.add_message("line", event["sender"], "system", event["body"])
        if event.get("to"):
            audience = "me" if event["to"] == HOUR["agent"] else "other"
            self.db._exec("UPDATE messages SET audience_attachment_id=? WHERE id=?",
                          (audience, message["id"]))
        return self.db.messages_by_ids("line", [message["id"]])[0]

    def test_every_fixture_notice_has_the_class_its_author_gave_it(self):
        for event in HOUR["events"]:
            with self.subTest(body=event["body"][:60]):
                self.assertEqual(classify(self.post(event)), event["class"])

    def test_a_process_is_pasted_only_the_needs_action_notices_of_the_hour(self):
        for event in HOUR["events"]:
            self.post(event)
        pasted = [m["body"] for m in digest_candidates(self.db, "line", 0, HOUR["agent"], "me")]
        expected = [e["body"] for e in HOUR["events"] if e["class"] == "needs-action"
                    and e.get("to") in (None, HOUR["agent"])]
        self.assertEqual(sorted(pasted), sorted(expected))

    def test_people_still_read_every_notice_in_the_line(self):
        for event in HOUR["events"]:
            self.post(event)
        stored = [m for m in self.db.messages_after("line", 0) if m["sender_type"] == "system"]
        self.assertEqual(len(stored), len(HOUR["events"]))
        self.assertEqual(sum(1 for m in stored if "waiting, not stalled" in m["body"]), 6)

    def test_an_unknown_system_notice_and_every_other_speaker_are_needs_action(self):
        self.assertEqual(classify({"sender_type": "system", "body": "⚠ something new broke"}),
                         "needs-action")
        self.assertEqual(classify({"sender_type": "human", "body": "⏳ waiting, not stalled: x"}),
                         "needs-action")
        self.assertEqual(classify({"sender_type": "agent", "body": "☺ a reacted 👍 to your «x»"}),
                         "needs-action")

    def test_a_negative_reaction_is_still_pasted(self):
        body = "☺ greg reacted ❌ to your «done» — no reply needed unless this raises something new"
        self.assertEqual(classify({"sender_type": "system", "body": body,
                                   "audience_attachment_id": "me"}), "needs-action")
        self.assertTrue(is_reaction_notice({"sender_type": "system", "body": body,
                                            "audience_attachment_id": "me"}))

    def test_a_private_copy_of_a_public_notice_is_not_dropped(self):
        replaced = "↻ @impl replaced with a fresh instance (by @cap): rot — assign now"
        self.assertEqual(classify({"sender_type": "system", "body": replaced}), "informational")
        self.assertEqual(classify({"sender_type": "system", "body": replaced,
                                   "audience_attachment_id": "me"}), "needs-action")

    def test_resume_keeps_the_addressed_instruction_and_drops_the_addressed_echo(self):
        self.post({"sender": "system", "to": HOUR["agent"], "body":
                   "☺ greg reacted 👍 to your «x» — no reply needed unless this raises something new"})
        self.post({"sender": "system", "to": HOUR["agent"], "body": "⚠ @impl-11ed30 is thrashing: act"})
        runtime = type("R", (), {"db": self.db})()
        att = self.db.get_attachment("me")
        self.assertEqual([m["body"] for m in addressed_backlog(runtime, att)],
                         ["⚠ @impl-11ed30 is thrashing: act"])


if __name__ == "__main__":
    unittest.main()
