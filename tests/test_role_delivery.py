"""A role grant/revocation updates knowledge on the next existing wake, not a new turn."""

import unittest
from unittest.mock import patch

from types import SimpleNamespace

from partyline.role_delivery import RoleState, bind_role_delivery

NO_GOAL = SimpleNamespace(get_conversation=lambda conv_id: {"goal": ""}, list_presets=lambda: [],
                          list_attachments=lambda conv_id: [])


class RoleDeliveryTests(unittest.TestCase):
    def test_live_grant_and_revocation_are_seen_once_per_change(self):
        ordinary = RoleState("implementer", "line", None, ("read", "write"))
        manager = RoleState("lead", "line", None, ("read", "write", "assign", "create_child"))
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=ordinary) as role:
            bind_role_delivery(NO_GOAL, att)
            self.assertEqual(att["role_briefing"], "")
            self.assertEqual(att["digest_rider"](), "task board")
            role.return_value = manager
            self.assertIn("Captain pack", att["digest_rider"]())
            later = att["digest_rider"]()
            self.assertIn("captain pack: GET /api/conversations/line/briefing", later)
            self.assertNotIn("## Captain pack", later)
            role.return_value = ordinary
            self.assertIn("ordinary participant", att["digest_rider"]())
            self.assertEqual(att["digest_rider"](), "task board")

    def test_a_detached_captain_teaches_nobody_a_handoff(self):
        ordinary = RoleState("implementer", "line", None, ("read", "write"))
        handoff = RoleState("implementer", "line", None, ("read", "write", "appoint_lead"))
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=ordinary) as role:
            bind_role_delivery(NO_GOAL, att)
            role.return_value = handoff
            self.assertNotIn("handoff", att["digest_rider"]().lower())

    def test_a_worker_briefed_under_a_live_captain_is_told_not_to_push(self):
        captained = RoleState("implementer", "line", None, ("read", "write"), captained=True)
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=captained):
            bind_role_delivery(NO_GOAL, att)
        self.assertIn("## Worker pack", att["role_briefing"])
        self.assertIn("Commit locally", att["role_briefing"])
        self.assertNotIn("## Captain pack", att["role_briefing"])

    def test_a_worker_rider_rebriefs_when_a_captain_appears_and_goes(self):
        worker = RoleState("implementer", "line", None, ("read", "write"))
        captained = RoleState("implementer", "line", None, ("read", "write"), captained=True)
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=worker) as role:
            bind_role_delivery(NO_GOAL, att)
            self.assertEqual(att["role_briefing"], "")
            self.assertNotIn("Worker pack", att["digest_rider"]())
            role.return_value = captained
            self.assertIn("Worker pack", att["digest_rider"]())
            role.return_value = worker
            self.assertIn("ordinary participant", att["digest_rider"]())

    def test_a_demoted_captain_keeps_the_scope_warning_next_to_the_worker_pack(self):
        captain = RoleState("lead", "line", None, ("assign", "create_child"))
        worker = RoleState("implementer", "line", None, ("read", "write"), captained=True)
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=captain) as role:
            bind_role_delivery(NO_GOAL, att)
            role.return_value = worker
            rider = att["digest_rider"]()
        self.assertIn("## Worker pack", rider)
        self.assertIn("Your current role is ordinary participant, not captain", rider)

    def test_resumed_manager_learns_tools_without_a_new_joining_briefing(self):
        manager = RoleState("lead", "line", "parent", ("assign", "create_child", "report"))
        att = {"id": "worker", "resume": True, "digest_rider": lambda: "helper command"}
        with patch("partyline.role_delivery.current_role", return_value=manager):
            bind_role_delivery(NO_GOAL, att)
            first = att["digest_rider"]()
            self.assertIn("helper command", first)
            self.assertIn("by @mention from this line", first)
            self.assertIn("captain pack: GET /api/conversations/line/briefing",
                          att["digest_rider"]())

    def test_a_captained_worker_gets_the_reminder_once_per_role_state(self):
        captained = RoleState("implementer", "line", None, ("read", "write"), captained=True)
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=captained):
            bind_role_delivery(NO_GOAL, att)
            first = att["digest_rider"]()
            again = att["digest_rider"]()
        self.assertTrue(first.startswith("task board\n(you are a worker on a captained line: "
                                         "edit only on your captain's @mention"))
        self.assertIn("the goal above is context, not your assignment", first)
        self.assertEqual(again, "task board")

    def test_captain_riders_send_only_changed_real_state(self):
        manager = RoleState("lead", "line", None, ("assign",), staffed=True)
        long_goal = "(goal you are seeing through: " + "ship " * 500 + "; you are the captain)"
        staffing = "(staffing — in use: " + "; ".join(f"worker-{n} «line»" for n in range(4)) + ")"
        handoffs = "(hand-off: " + "; ".join(
            f"«slice-{n}» accepted {'a' * 12} worktree /tmp/slice-{n}" for n in range(10)
        ) + ")"
        att = {"id": "lead", "digest_rider": lambda: ""}
        with patch("partyline.role_delivery.current_role", return_value=manager), \
                patch("partyline.role_delivery.goal_rider", return_value=long_goal) as goal, \
                patch("partyline.role_delivery.staffing_line", return_value=staffing), \
                patch("partyline.role_delivery.handoff_rider", return_value=handoffs):
            bind_role_delivery(NO_GOAL, att)
            first = att["digest_rider"]()
            repeat = att["digest_rider"]()
            goal.return_value = long_goal + " changed"
            changed = att["digest_rider"]()
        self.assertIn(long_goal, first)
        self.assertIn(staffing, first)
        self.assertIn(handoffs, first)
        self.assertIn("captain pack: GET /api/conversations/line/briefing", repeat)
        self.assertNotIn(long_goal, repeat)
        self.assertNotIn(staffing, repeat)
        self.assertNotIn(handoffs, repeat)
        self.assertIn(long_goal + " changed", changed)
        self.assertNotIn(staffing, changed)
        self.assertNotIn(handoffs, changed)

    def test_staffing_state_change_does_not_redeliver_the_captain_pack(self):
        ordinary = RoleState("implementer", "line", None, ("read", "write"))
        captain = RoleState("lead", "line", None, ("assign",), staffed=False)
        staffed = RoleState("lead", "line", None, ("assign",), staffed=True)
        att = {"id": "lead", "digest_rider": lambda: ""}
        with patch("partyline.role_delivery.current_role",
                   side_effect=[ordinary, captain, staffed]), \
                patch("partyline.role_delivery.goal_rider", return_value=""), \
                patch("partyline.role_delivery.handoff_rider", return_value=""), \
                patch("partyline.role_delivery.staffing_line",
                      side_effect=["(staffing — in use: nobody)", "(staffing — in use: worker)"]):
            bind_role_delivery(NO_GOAL, att)
            first_captain_wake = att["digest_rider"]()
            staffing_change = att["digest_rider"]()
        self.assertIn("## Captain pack", first_captain_wake)
        self.assertIn("(staffing — in use: worker)", staffing_change)
        self.assertNotIn("## Captain pack", staffing_change)

    def test_clearing_rider_state_is_an_observable_delta(self):
        captain = RoleState("lead", "line", None, ("assign",))
        att = {"id": "lead", "digest_rider": lambda: ""}
        with patch("partyline.role_delivery.current_role", return_value=captain), \
                patch("partyline.role_delivery.goal_rider", side_effect=["(goal: ship)", ""]), \
                patch("partyline.role_delivery.staffing_line",
                      side_effect=["(staffing — in use: worker)", ""]), \
                patch("partyline.role_delivery.handoff_rider",
                      side_effect=["(hand-off: «slice» accepted abc)", ""]):
            bind_role_delivery(NO_GOAL, att)
            att["digest_rider"]()
            cleared = att["digest_rider"]()
        self.assertIn("(goal cleared)", cleared)
        self.assertIn("(staffing cleared)", cleared)
        self.assertIn("(hand-offs cleared)", cleared)

    def test_permission_change_for_a_worker_does_not_repeat_its_pack_or_reminder(self):
        first_state = RoleState("implementer", "line", None, ("read",), captained=True)
        changed_state = RoleState("implementer", "line", None, ("read", "write"), captained=True)
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role",
                   side_effect=[first_state, first_state, changed_state]):
            bind_role_delivery(NO_GOAL, att)
            att["digest_rider"]()
            changed = att["digest_rider"]()
        self.assertEqual(changed, "task board")
        self.assertNotIn("## Worker pack", changed)
        self.assertNotIn("you are a worker on a captained line", changed)

    def test_the_worker_reminder_never_rides_a_captain_or_an_uncaptained_process(self):
        captain = RoleState("lead", "line", None, ("read", "write", "assign", "create_child"))
        uncaptained = RoleState("implementer", "line", None, ("read", "write"))
        for label, state in {"captain": captain, "uncaptained": uncaptained}.items():
            with self.subTest(label):
                att = {"id": "p", "digest_rider": lambda: "task board"}
                with patch("partyline.role_delivery.current_role", return_value=state):
                    bind_role_delivery(NO_GOAL, att)
                    rider = att["digest_rider"]()
                self.assertNotIn("you are a worker on a captained line", rider)

    def test_a_worker_woken_after_a_late_captain_gets_the_pack_and_the_reminder_together(self):
        worker = RoleState("implementer", "line", None, ("read", "write"))
        captained = RoleState("implementer", "line", None, ("read", "write"), captained=True)
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=worker) as role:
            bind_role_delivery(NO_GOAL, att)
            self.assertEqual(att["digest_rider"](), "task board")
            role.return_value = captained
            rider = att["digest_rider"]()
        self.assertIn("## Worker pack", rider)
        self.assertIn("act only on your captain's @mention", rider)
        self.assertIn("you are a worker on a captained line", rider)
