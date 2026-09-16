"""Hierarchy knowledge is given only to roles that can use it."""

import unittest

from partyline import features
from partyline.role_briefing import role_instructions, worker_instructions


class RoleBriefingTests(unittest.TestCase):
    def test_ordinary_participant_gets_no_hierarchy_instructions(self):
        self.assertEqual(role_instructions(["read", "write"], "line", "parent"), "")

    def test_a_participant_is_never_taught_to_appoint_a_captain(self):
        text = role_instructions(["read", "write", "appoint_lead"], "line", None)
        self.assertEqual(text, "")

    def test_root_manager_gets_delegation_but_no_parent_reporting_playbook(self):
        text = role_instructions(["assign", "create_child", "read_reports"], "root", None)
        self.assertIn("/api/conversations/root/children", text)
        self.assertIn("/api/conversations/root/reports", text)
        self.assertIn("PUT /api/conversations/root/goal", text)
        self.assertIn("### Staffing", text)
        self.assertIn("/api/conversations/root/staffing", text)
        self.assertIn("can_manage captains", text)
        self.assertIn("### You are the captain; you do not implement", text)
        self.assertIn("### The loop you run", text)
        self.assertIn("### Ask the person first", text)
        self.assertIn("### Worked example", text)
        self.assertNotIn("/api/heartbeat", text)  # off by default since 1.23.0
        with features.overridden(heartbeat=True):
            on = role_instructions(["assign", "create_child", "read_reports"], "root", None)
        self.assertIn("/api/heartbeat", on)
        self.assertNotIn('"notify":true', text)
        self.assertNotIn("also a child manager", text)

    def test_child_manager_learns_that_a_mention_wakes_and_a_report_does_not(self):
        text = role_instructions(["assign", "create_child", "read_reports", "report"], "child", "root", 1)
        self.assertIn("POST /api/conversations/child/reports", text)
        self.assertIn("by @mention from this line", text)
        self.assertIn("without waking anyone", text)
        self.assertNotIn('"notify":true', text)

    def test_a_captain_is_told_its_depth_and_what_a_child_may_do(self):
        root = role_instructions(["assign", "create_child"], "root", None, 0)
        self.assertIn("depth 0 of 2; a child of yours may split once more", root)
        self.assertIn("Work goes down, not sideways", root)
        mid = role_instructions(["assign", "create_child"], "mid", "root", 1)
        self.assertIn("depth 1 of 2; a child of yours is a leaf", mid)

    def test_a_leaf_captain_keeps_the_pack_and_staffs_its_own_line(self):
        text = role_instructions(["assign", "report"], "leaf", "mid", 2)
        self.assertIn("### You are the captain; you do not implement", text)
        self.assertIn("**This line is a leaf** (depth 2 of 2)", text)
        self.assertIn("POST /api/conversations/leaf/attachments", text)
        self.assertIn("/api/conversations/leaf/staffing", text)
        self.assertNotIn("/children", text)
        self.assertIn("also a child manager", text)

    def test_a_staffed_captain_is_told_to_assign_its_workers_at_any_depth(self):
        text = role_instructions(["assign", "report"], "mid", "root", 1, staffed=True)
        self.assertIn("### You are the captain; you do not implement", text)
        self.assertIn("Workers already on your line are yours: assign them.", text)
        self.assertIn("**This line is staffed** (depth 1 of 2)", text)
        self.assertIn("/api/conversations/mid/staffing", text)
        self.assertNotIn("/children", text)
        self.assertNotIn("This line is a leaf", text)
        self.assertIn("also a child manager", text)

    def test_missing_report_capability_does_not_advertise_report_tools(self):
        text = role_instructions(["assign", "create_child"], "child", "root", 1)
        self.assertNotIn("/reports", text)

    def test_the_acceptance_step_requires_a_completed_review_before_reporting(self):
        text = role_instructions(["assign"], "root", None)
        review = text.index("skills/adversarial-review/SKILL.md")
        self.assertLess(review, text.index("Tell the person once"))
        self.assertIn("Receipt is not acceptance", text)
        self.assertIn("a child line's branch/report and a same-line worker's hand-off", text)
        self.assertIn("Run it or delegate it", text)
        step = text[text.index("Ensure an adversarial review"):text.index("Tell the person once")]
        self.assertNotIn("personally", step)
        self.assertNotIn("yourself", step)

    def test_every_captain_variant_carries_both_the_review_and_push_rules(self):
        packs = {
            "splitting": role_instructions(
                ["assign", "create_child", "read_reports"], "root", None),
            "leaf": role_instructions(["assign", "report"], "leaf", "mid", 2),
            "staffed": role_instructions(
                ["assign", "report"], "mid", "root", 1, staffed=True),
        }
        for label, text in packs.items():
            with self.subTest(label):
                self.assertIn("skills/adversarial-review/SKILL.md", text)
                self.assertIn("only you push", text)
                self.assertNotIn("## Worker pack", text)

    def test_the_read_reports_block_turns_receipt_into_a_review_at_the_sha(self):
        text = role_instructions(["assign", "create_child", "read_reports"], "root", None)
        self.assertIn("/api/conversations/root/reports", text)
        self.assertIn("have the child's work reviewed at its exact SHA", text)

    def test_a_worker_on_a_captained_line_commits_locally_and_hands_the_sha_up(self):
        text = worker_instructions(captained=True)
        self.assertIn("## Worker pack", text)
        self.assertIn("Commit locally", text)
        self.assertIn("hand the captain the commit SHA", text)
        self.assertIn("do not push", text)
        self.assertNotIn("## Captain pack", text)
        self.assertNotIn("You are the captain", text)

    def test_a_worker_on_an_uncaptained_line_is_told_nothing_new(self):
        self.assertEqual(worker_instructions(captained=False), "")
