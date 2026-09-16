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
            self.assertEqual(att["digest_rider"](), "task board\n(you are the captain — delegate to a "
                             "sub-captain, review, decide; you do not implement)")
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
            self.assertTrue(att["digest_rider"]().startswith("helper command\n(you are the captain"))
