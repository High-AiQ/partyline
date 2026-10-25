"""The memory warning names what is growing, grouped by command, not one process at a time."""

import pathlib
import unittest
from unittest.mock import patch

from partyline.goal import MAX_GOAL
from partyline.memory_warning import format_top, warning_text
import os

from partyline.top_processes import GROUP_LIMIT, argv, namespace_pid, process_breakdown, render

ROOT = pathlib.Path(__file__).resolve().parent.parent
# claude (10) owns a browser (11) with two renderers (13, 14), a node tool (12) and a lone
# daemon (15) outside the tree; 10 itself must never be named as a culprit.
PARENTS = {10: 1, 11: 10, 12: 10, 13: 11, 14: 11, 15: 1}
RSS = {10: 500, 11: 100, 12: 40, 13: 300, 14: 200, 15: 9000}
COMMANDS = {10: ["/usr/bin/claude"], 11: ["/opt/chrome/chrome"],
            12: ["node", "tool.js"], 13: ["/opt/chrome/chrome", "--type=renderer"],
            14: ["/opt/chrome/chrome", "--type=gpu-process"], 15: ["sshd"]}


class BreakdownTest(unittest.TestCase):
    def breakdown(self, limit=GROUP_LIMIT):
        with patch("partyline.top_processes.sys.platform", "linux"), \
                patch("partyline.top_processes.argv", lambda pid: COMMANDS[pid]), \
                patch("partyline.top_processes.namespace_pid", lambda pid: pid + 1000):
            return process_breakdown(10, limit=limit, snapshot=(PARENTS, RSS))

    def test_members_group_by_command_with_counts_and_largest_pid(self):
        groups = self.breakdown()
        self.assertEqual([group["command"] for group in groups], ["chrome", "node"])
        chrome = groups[0]
        self.assertEqual((chrome["count"], chrome["rss"]), (3, 100 + 300 + 200))
        self.assertEqual(chrome["pid"], 1013)
        self.assertEqual(chrome["cmdline"], "/opt/chrome/chrome --type=renderer")
        self.assertEqual((groups[1]["count"], groups[1]["rss"], groups[1]["pid"]), (1, 40, 1012))

    def test_root_and_outside_processes_are_not_named(self):
        names = {group["command"] for group in self.breakdown()}
        self.assertNotIn("claude", names)
        self.assertNotIn("sshd", names)

    def test_limit_keeps_the_biggest_groups(self):
        self.assertEqual([g["command"] for g in self.breakdown(limit=1)], ["chrome"])

    def test_other_platforms_and_unreadable_tables_name_nothing(self):
        with patch("partyline.top_processes.sys.platform", "darwin"):
            self.assertEqual(process_breakdown(10, snapshot=(PARENTS, RSS)), [])
        with patch("partyline.top_processes.sys.platform", "linux"), \
                patch("partyline.memory_sampler.process_snapshot", return_value=None):
            self.assertEqual(process_breakdown(10), [])

    def test_empty_argv_reads_as_a_question_mark_and_long_lines_are_cut(self):
        self.assertEqual(render([]), "?")
        self.assertEqual(len(render(["x" * 200])), 60)
        self.assertTrue(render(["x" * 200]).endswith("…"))

    def test_warning_text_shows_the_grouped_breakdown_for_both_readers(self):
        groups = self.breakdown()
        text = format_top(groups)
        self.assertIn("3× chrome", text)
        self.assertIn("largest pid 1013", text)
        self.assertIn("node", text)
        self.assertNotIn("1×", text)  # a lone process is named without a count
        row = {"id": "att", "name": "worker"}
        for own in (True, False):
            warning = warning_text(row, 3 * 1024**3, 4 * 1024**3, own=own, top=groups)
            self.assertIn("3× chrome", warning)
        self.assertEqual(format_top([]), "")


class ProcReadTest(unittest.TestCase):
    def test_own_argv_and_namespace_pid_come_from_proc(self):
        self.assertTrue(argv(os.getpid()))
        self.assertEqual(namespace_pid(os.getpid()), os.getpid())

    def test_a_vanished_process_reads_as_empty_and_keeps_its_host_pid(self):
        gone = 2**22 + 12345
        self.assertEqual(argv(gone), [])
        self.assertEqual(namespace_pid(gone), gone)
        self.assertEqual(render(argv(gone)), "?")


class TaskBriefDocTest(unittest.TestCase):
    def test_brief_pattern_doc_names_the_real_goal_cap(self):
        text = (ROOT / "docs" / "task-briefs.md").read_text(encoding="utf-8")
        self.assertEqual(MAX_GOAL, 3000)
        self.assertIn(f"{MAX_GOAL} characters", text)
        self.assertIn("create_task", text)
        self.assertIn("committed file", text)
        self.assertIn("base='upstream'", text)


if __name__ == "__main__":
    unittest.main()
