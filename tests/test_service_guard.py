"""The service OOM guard is checked from systemd's effective properties."""

import os
import subprocess
import unittest
from unittest.mock import mock_open, patch

from partyline import service_guard


class ServiceGuardTest(unittest.TestCase):
    def test_accepts_continue_policy_and_a_limit_below_host_ram(self):
        result = service_guard.check_properties(
            {"OOMPolicy": "continue", "MemoryMax": str(40 * 1024**3)},
            64 * 1024**3,
            "partyline.service",
        )
        self.assertEqual(result, (True, "", ""))

    def test_reports_exact_drop_in_when_policy_or_memory_limit_is_unsafe(self):
        ok, reason, remedy = service_guard.check_properties(
            {"OOMPolicy": "stop", "MemoryMax": "infinity"},
            64 * 1024**3,
            "partyline.service",
        )
        self.assertFalse(ok)
        self.assertIn("OOMPolicy=continue", reason)
        self.assertIn("MemoryMax", reason)
        self.assertIn("~/.config/systemd/user/partyline.service.d/oom.conf", remedy)
        self.assertIn("[Service]\nOOMPolicy=continue\nMemoryMax=40G", remedy)
        self.assertIn("systemctl --user daemon-reload", remedy)
        self.assertIn("file a Partyline restart request", remedy)
        self.assertNotIn("systemctl --user restart", remedy)

    def test_extracts_the_attached_user_service_from_cgroup(self):
        self.assertEqual(
            service_guard.unit_from_cgroup(
                "0::/user.slice/user-1000.slice/user@1000.service/app.slice/partyline.service"
            ),
            "partyline.service",
        )

    def test_excludes_the_user_manager_cgroup_for_an_ordinary_doctor_process(self):
        self.assertIsNone(service_guard.unit_from_cgroup(
            "0::/user.slice/user-1000.slice/user@1000.service"
        ))

    def test_doctor_from_user_manager_cgroup_discovers_running_partyline_service(self):
        listing = subprocess.CompletedProcess(
            [], 0,
            "partyline.service loaded active running Partyline LAN instance\n",
            "",
        )
        properties = subprocess.CompletedProcess(
            [], 0, "OOMPolicy=continue\nMemoryMax=42949672960\n", "",
        )
        with patch(
            "builtins.open",
            mock_open(read_data="0::/user.slice/user-1000.slice/user@1000.service\n"),
        ), \
                patch.object(service_guard, "_host_memory_bytes", return_value=64 * 1024**3), \
                patch.object(service_guard.subprocess, "run", side_effect=[listing, properties]) as run, \
                patch.dict(os.environ, {"PARTYLINE_SYSTEMD_UNIT": ""}):
            self.assertEqual(service_guard.probe(), (True, "", ""))
        self.assertIn("list-units", run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0][3], "partyline.service")

    def test_boot_does_not_use_doctor_override_outside_service_cgroup(self):
        properties = subprocess.CompletedProcess(
            [], 0, "OOMPolicy=continue\nMemoryMax=42949672960\n", "",
        )
        with patch(
            "builtins.open",
            mock_open(read_data="0::/user.slice/user-1000.slice/user@1000.service\n"),
        ), \
                patch.object(service_guard, "_host_memory_bytes", return_value=64 * 1024**3), \
                patch.object(service_guard.subprocess, "run", return_value=properties) as run, \
                patch("partyline.server_memory.verify", return_value=(False, "no server cap")), \
                patch.dict(os.environ, {"PARTYLINE_SYSTEMD_UNIT": "partyline.service"}):
            service_unit = service_guard.unit_from_cgroup()
            result = service_guard.probe(service_unit, discover=False)

        self.assertFalse(result[0])
        self.assertIn("not in this process cgroup", result[1])
        self.assertIn("partyline.service.d/oom.conf", result[2])
        run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
