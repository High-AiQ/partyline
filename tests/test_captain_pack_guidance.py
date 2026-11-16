"""Captains and suite lines are told plainly what full tasks may run, and when to post status."""

import unittest

from partyline.mcp.descriptions import LINE, SHORT
from partyline.mcp.tools_tasks import _DESCRIBE
from partyline.orchestrator_suite import SUITE
from partyline.pack_blocks import ORCHESTRATOR

LANE = "full and express tasks never run the end-to-end lane"


class CaptainGuidanceTest(unittest.TestCase):
    def test_the_captain_pack_states_the_lane_rule_near_its_top(self):
        self.assertIn(LANE, ORCHESTRATOR)
        self.assertIn("never take a lease meant for the suite", ORCHESTRATOR)
        self.assertIn("never re-point shared dev infrastructure", ORCHESTRATOR)
        self.assertLess(ORCHESTRATOR.index(LANE), 400)

    def test_the_captain_pack_asks_for_a_status_before_long_waits(self):
        self.assertIn("before any wait longer than about 10 minutes", ORCHESTRATOR)

    def test_create_task_states_the_lane_rule_in_full(self):
        self.assertIn("Full and express tasks never run the end-to-end lane", _DESCRIBE["create_task"])
        self.assertIn("never take a lease meant for the suite", _DESCRIBE["create_task"])

    def test_the_create_task_listing_line_states_the_rule_within_its_limit(self):
        self.assertIn("e2e", SHORT["create_task"])
        self.assertLessEqual(len(SHORT["create_task"]), LINE)

    def test_suite_lines_post_progress_beats_during_long_runs(self):
        self.assertIn("progress beats", SUITE)
        self.assertIn("N/M suites done", SUITE)
