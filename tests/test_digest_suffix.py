"""The repeating suffix lines ride when new, changed or unproven, and every Nth time."""

import os
import tempfile
import unittest
from unittest.mock import patch

from partyline.adapters.briefing import DIGEST_FOOTER, format_digest
from partyline.db import Db
from partyline.digest_suffix import EVERY, SuffixGate, begin_gate
from partyline.role_delivery import RoleState, bind_role_delivery


def msg(ident):
    return [{"id": ident, "sender": "cap", "body": "go", "sender_type": "agent"}]


def digest(gate, ident, credited, git="(cwd git: abc clean)"):
    gate.begin(msg(ident), credited)
    with patch("partyline.adapters.briefing.cwd_git_digest", lambda _cwd: git):
        return format_digest(msg(ident), "", "/x", gate=gate)


class GatePerAttachmentTest(unittest.TestCase):
    """The count lives on the attachment's in-memory dict: a restart or rotation starts again."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Db(os.path.join(directory.name, "x.db"))
        self.addCleanup(self.db.close)

    def bind(self, att_id):
        att = {"id": att_id, "digest_rider": lambda: ""}
        role = RoleState("worker", "root", None, ("read",))
        with patch("partyline.role_delivery.current_role", return_value=role):
            bind_role_delivery(self.db, att)
        return att

    def test_each_attachment_counts_its_own_deliveries(self):
        one, two = self.bind("one"), self.bind("two")
        self.assertIsNot(one["suffix_gate"], two["suffix_gate"])
        digest(one["suffix_gate"], 1, 0)
        digest(one["suffix_gate"], 2, 1)
        self.assertEqual((one["suffix_gate"].deliveries, two["suffix_gate"].deliveries), (2, 0))
        self.assertIn(DIGEST_FOOTER, digest(two["suffix_gate"], 1, 0))

    def test_a_compaction_makes_the_next_delivery_carry_every_line_again(self):
        att = self.bind("one")
        gate = att["suffix_gate"]
        with patch("partyline.adapters.briefing.cwd_git_digest", lambda _cwd: "(cwd git: abc clean)"):
            for ident in (1, 2):
                gate.begin(msg(ident), ident - 1, att["compaction_count"]())
                body = format_digest(msg(ident), "", "/x", gate=gate)
            self.assertEqual(body, "[cap]: go")
            self.db._exec("INSERT INTO compaction_events(attachment_id, runtime_owner, trigger,"
                          " turn, created_at) VALUES('one','o','auto',1,1)")
            gate.begin(msg(3), 2, att["compaction_count"]())
            after = format_digest(msg(3), "", "/x", gate=gate)
        self.assertIn("(cwd git: abc clean)", after)
        self.assertIn(DIGEST_FOOTER, after)

    def test_a_vanished_attachment_row_credits_nothing_instead_of_failing(self):
        att = self.bind("never-stored")
        self.assertEqual(att["credited_through"](), 0)
        self.assertEqual(att["compaction_count"](), 0)

    def test_a_restart_or_rotated_session_binds_a_new_gate_with_the_full_suffix(self):
        before = self.bind("one")
        digest(before["suffix_gate"], 1, 0)
        self.assertEqual(digest(before["suffix_gate"], 2, 1), "[cap]: go")
        after = self.bind("one")  # the adapter is rebuilt: same attachment, new process
        self.assertIsNot(after["suffix_gate"], before["suffix_gate"])
        self.assertEqual(after["suffix_gate"].deliveries, 0)
        self.assertIn(DIGEST_FOOTER, digest(after["suffix_gate"], 3, 2))


class SuffixGateTest(unittest.TestCase):
    def test_the_first_delivery_carries_every_line_then_none(self):
        gate = SuffixGate()
        first = digest(gate, 1, 0)
        self.assertIn("(cwd git: abc clean)", first)
        self.assertIn(DIGEST_FOOTER, first)
        self.assertEqual(digest(gate, 2, 1), "[cap]: go")

    def test_a_changed_line_rides_again_and_only_it(self):
        gate = SuffixGate()
        digest(gate, 1, 0)
        again = digest(gate, 2, 1, git="(cwd git: def dirty)")
        self.assertIn("(cwd git: def dirty)", again)
        self.assertNotIn(DIGEST_FOOTER, again)

    def test_a_line_whose_carrier_was_never_proven_is_sent_again(self):
        gate = SuffixGate()
        digest(gate, 5, 0)
        self.assertIn(DIGEST_FOOTER, digest(gate, 6, 4))  # delivery 5 is not credited yet
        self.assertNotIn(DIGEST_FOOTER, digest(gate, 7, 6))

    def test_an_unnumbered_digest_always_carries_the_lines(self):
        gate = SuffixGate()
        gate.begin([{"sender": "system", "body": "x"}], 0)
        self.assertEqual(gate.keep("footer", "f"), "f")
        gate.begin([{"sender": "system", "body": "x"}], 99)
        self.assertEqual(gate.keep("footer", "f"), "f")

    def test_a_long_session_is_still_reminded_every_nth_delivery(self):
        gate = SuffixGate()
        carried = [DIGEST_FOOTER in digest(gate, n, n - 1) for n in range(1, 2 * EVERY + 2)]
        self.assertEqual([n + 1 for n, yes in enumerate(carried) if yes], [1, 1 + EVERY, 1 + 2 * EVERY])

    def test_no_gate_means_every_delivery_carries_everything(self):
        self.assertIn(DIGEST_FOOTER, format_digest(msg(1), "", ""))
        self.assertIsNone(begin_gate({}, msg(1)))

    def test_an_empty_line_is_never_sent(self):
        gate = SuffixGate()
        gate.begin(msg(1), 0)
        self.assertEqual(gate.keep("cwd", ""), "")


if __name__ == "__main__":
    unittest.main()
