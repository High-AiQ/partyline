"""A role grant/revocation updates knowledge on the next existing wake, not a new turn."""

import unittest
from unittest.mock import patch

from partyline.role_delivery import RoleState, bind_role_delivery


class RoleDeliveryTests(unittest.TestCase):
    def test_live_grant_and_revocation_are_seen_once_per_change(self):
        ordinary = RoleState("implementer", "line", None, ("read", "write"))
        manager = RoleState("lead", "line", None, ("read", "write", "create_child"))
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=ordinary) as role:
            bind_role_delivery(object(), att)
            self.assertEqual(att["role_briefing"], "")
            self.assertEqual(att["digest_rider"](), "task board")
            role.return_value = manager
            self.assertIn("Manager tools", att["digest_rider"]())
            self.assertEqual(att["digest_rider"](), "task board")
            role.return_value = ordinary
            self.assertIn("ordinary participant", att["digest_rider"]())
            self.assertEqual(att["digest_rider"](), "task board")

    def test_participant_learns_the_handoff_when_the_manager_detaches(self):
        ordinary = RoleState("implementer", "line", None, ("read", "write"))
        handoff = RoleState("implementer", "line", None, ("read", "write", "appoint_lead"))
        att = {"id": "worker", "digest_rider": lambda: "task board"}
        with patch("partyline.role_delivery.current_role", return_value=ordinary) as role:
            bind_role_delivery(object(), att)
            role.return_value = handoff
            self.assertIn("Manager handoff", att["digest_rider"]())

    def test_resumed_manager_learns_tools_without_a_new_joining_briefing(self):
        manager = RoleState("lead", "line", "parent", ("create_child", "report"))
        att = {"id": "worker", "resume": True, "digest_rider": lambda: "helper command"}
        with patch("partyline.role_delivery.current_role", return_value=manager):
            bind_role_delivery(object(), att)
            first = att["digest_rider"]()
            self.assertIn("helper command", first)
            self.assertIn('"notify":true', first)
            self.assertEqual(att["digest_rider"](), "helper command")
