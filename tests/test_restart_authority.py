"""Full-instance planning is authorized as a whole, never silently narrowed."""

import unittest
from unittest.mock import Mock, patch

from partyline.auth_guard import Principal
from partyline.machine_scope import allows_restart_plan


class RestartAuthorityTests(unittest.TestCase):
    def test_fleet_requires_authority_over_every_line(self):
        principal = Principal(kind="machine", name="lead", conv_id="parent",
                              attachment_id="a", is_lead=True)
        db = Mock()
        db.list_conversations.return_value = [{"id": "parent"}, {"id": "unrelated"}]
        db.list_attachments.return_value = [{"status": "running"}]
        with patch("partyline.machine_scope.allows", side_effect=[True, False]):
            self.assertFalse(allows_restart_plan(principal, "parent", db=db, scope="all"))
        with patch("partyline.machine_scope.allows", return_value=True):
            self.assertTrue(allows_restart_plan(principal, "parent", db=db, scope="all"))

    def test_implementer_can_plan_home_but_not_fleet_or_other_owner(self):
        principal = Principal(kind="machine", name="worker", conv_id="home", attachment_id="a")
        self.assertTrue(allows_restart_plan(principal, "home"))
        self.assertFalse(allows_restart_plan(principal, "other"))
        self.assertFalse(allows_restart_plan(principal, "home", db=Mock(), scope="all"))

    def test_human_retains_full_instance_authority(self):
        principal = Principal(kind="user", name="operator", user_id="u")
        self.assertTrue(allows_restart_plan(principal, "any", db=Mock(), scope="all"))

    def test_empty_unrelated_line_does_not_grant_or_block_fleet(self):
        principal = Principal(kind="machine", name="lead", conv_id="parent", attachment_id="a", is_lead=True)
        db = Mock()
        db.list_conversations.return_value = [{"id": "parent"}, {"id": "empty"}]
        db.list_attachments.side_effect = [[{"status": "running"}], [{"status": "detached"}]]
        with patch("partyline.machine_scope.allows", return_value=True) as allowed:
            self.assertTrue(allows_restart_plan(principal, "parent", db=db, scope="all"))
            allowed.assert_called_once_with(db, principal, "parent", "close")
