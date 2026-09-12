"""Hierarchy knowledge is given only to roles that can use it."""

import unittest

from partyline.role_briefing import role_instructions


class RoleBriefingTests(unittest.TestCase):
    def test_ordinary_participant_gets_no_hierarchy_instructions(self):
        self.assertEqual(role_instructions(["read", "write"], "line", "parent"), "")

    def test_participant_on_a_managerless_line_learns_the_handoff(self):
        text = role_instructions(["read", "write", "appoint_lead"], "line", None)
        self.assertIn("Manager handoff", text)
        self.assertIn("/api/conversations/line/lead", text)

    def test_root_manager_gets_delegation_but_no_parent_reporting_playbook(self):
        text = role_instructions(["create_child", "read_reports"], "root", None)
        self.assertIn("/api/conversations/root/children", text)
        self.assertIn("/api/conversations/root/reports", text)
        self.assertIn("PUT /api/conversations/root/goal", text)
        self.assertIn("### The loop you run", text)
        self.assertIn("### Ask the person first", text)
        self.assertIn("### Worked example", text)
        self.assertIn("/api/heartbeat", text)
        self.assertNotIn('"notify":true', text)
        self.assertNotIn("also a child manager", text)

    def test_child_manager_learns_that_a_mention_wakes_and_a_report_does_not(self):
        text = role_instructions(["create_child", "read_reports", "report"], "child", "root")
        self.assertIn("POST /api/conversations/child/reports", text)
        self.assertIn("by @mention from this line", text)
        self.assertIn("without waking anyone", text)
        self.assertNotIn('"notify":true', text)

    def test_missing_report_capability_does_not_advertise_report_tools(self):
        text = role_instructions(["create_child"], "child", "root")
        self.assertNotIn("/reports", text)
