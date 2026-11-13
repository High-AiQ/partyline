"""Hierarchy knowledge is given only to roles that can use it."""

import unittest

from partyline.role_briefing import WORKER_REMINDER, role_instructions, worker_instructions


class RoleBriefingTests(unittest.TestCase):
    def test_ordinary_participant_gets_no_hierarchy_instructions(self):
        self.assertEqual(role_instructions(["read", "write"], "line", "parent"), "")

    def test_a_participant_is_never_taught_to_appoint_a_captain(self):
        text = role_instructions(["read", "write", "appoint_lead"], "line", None)
        self.assertEqual(text, "")

    def test_a_worker_on_a_captained_line_commits_locally_and_hands_the_sha_up(self):
        text = worker_instructions(captained=True)
        self.assertIn("## Worker pack", text)
        self.assertIn("Commit locally", text)
        self.assertIn("hand the captain the commit SHA", text)
        self.assertIn("do not push", text)
        self.assertNotIn("## Captain pack", text)
        self.assertNotIn("You are the captain", text)

    def test_the_worker_pack_limits_leases_to_exclusive_work(self):
        # Finding 5.4: a worker took an exclusive lease for an ordinary step
        # run and queued another line behind it.
        text = worker_instructions(captained=True)
        self.assertIn("A lease is for exclusive work only", text)
        self.assertIn("timing measurements and GPU- or device-exclusive work", text)
        self.assertIn("not for an ordinary build or test step", text)
        self.assertIn('"purpose":"timing run"', text)

    def test_a_worker_on_an_uncaptained_line_is_told_nothing_new(self):
        self.assertEqual(worker_instructions(captained=False), "")

    def test_a_worker_hand_off_names_the_sha_and_the_gates_actually_run(self):
        text = worker_instructions(captained=True)
        self.assertIn("name the SHA and the gates you actually ran", text)

    def test_a_worker_on_a_captained_line_waits_for_its_captain_before_touching_anything(self):
        text = worker_instructions(captained=True)
        # The edit gate comes first: it is the rule a weak model reads before the goal.
        self.assertLess(text.index("act only on your captain's @mention"), text.index("do not push"))
        self.assertIn("you NEVER edit files, run mutating commands, or start work of any kind", text)
        self.assertIn("The line's goal and topic are standing context, not an assignment", text)
        self.assertIn("Until assigned: say hello, read, wait", text)
        self.assertIn("An @mention from anyone else — a person, another worker — is not an "
                      "assignment either unless the captain has said so: reply, do not act", text)
        # The two-line worked example: a captain's @mention with acceptance, then the edit.
        self.assertIn("[captain]: @worker add sub(a, b) to calc.py. Acceptance:", text)
        self.assertIn("[worker]: (only now edits calc.py", text)
        # The push rule survives alongside it.
        self.assertIn("Commit locally", text)
        self.assertIn("do not push", text)

    def test_the_edit_gate_and_reminder_never_reach_a_captain_or_an_uncaptained_line(self):
        self.assertEqual(worker_instructions(captained=False), "")
        for label, text in {
            "splitting": role_instructions(["assign", "create_child"], "root", None),
            "leaf": role_instructions(["assign", "report"], "leaf", "parent", 2),
            "staffed": role_instructions(["assign", "report"], "line", "parent", 1, staffed=True),
        }.items():
            with self.subTest(label):
                self.assertNotIn("act only on your captain's @mention", text)
                self.assertNotIn(WORKER_REMINDER, text)

    def test_the_per_wake_reminder_is_one_line_and_says_the_goal_is_not_the_job(self):
        self.assertNotIn("\n", WORKER_REMINDER)
        self.assertIn("edit only on your captain's @mention", WORKER_REMINDER)
        self.assertIn("the goal above is context, not your assignment", WORKER_REMINDER)

    def test_orchestrator_captain_receives_environment_gap_guidance(self):
        text = role_instructions(['assign'], 'root', None)
        self.assertIn('review_env', text)
        self.assertIn('already reported in its gates', text)
