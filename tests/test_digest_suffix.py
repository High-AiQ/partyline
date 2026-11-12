"""The repeating suffix lines ride when new, changed or unproven, and every Nth time."""

import unittest
from unittest.mock import patch

from partyline.adapters.briefing import DIGEST_FOOTER, format_digest
from partyline.digest_suffix import EVERY, SuffixGate, begin_gate


def msg(ident):
    return [{"id": ident, "sender": "cap", "body": "go", "sender_type": "agent"}]


def digest(gate, ident, credited, git="(cwd git: abc clean)"):
    gate.begin(msg(ident), credited)
    with patch("partyline.adapters.briefing.cwd_git_digest", lambda _cwd: git):
        return format_digest(msg(ident), "", "/x", gate=gate)


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
