"""The server raises its own open-file limit: macOS starts a process with 256."""

import sys
import unittest
from unittest.mock import patch

from partyline import fd_limit


class FakeResource:
    RLIMIT_NOFILE = 7
    RLIM_INFINITY = 2**63 - 1

    def __init__(self, soft, hard, refuse_above=None):
        self.limits, self.refuse_above, self.attempts = (soft, hard), refuse_above, []

    def getrlimit(self, which):
        assert which == self.RLIMIT_NOFILE
        return self.limits

    def setrlimit(self, which, limits):
        self.attempts.append(limits[0])
        if self.refuse_above is not None and limits[0] > self.refuse_above:
            raise ValueError("current limit exceeds maximum limit")
        self.limits = limits


class OpenFileLimitTests(unittest.TestCase):
    def test_macos_defaults_are_raised_to_what_the_kernel_allows(self):
        """256 soft, "unlimited" hard, and a kernel that refuses anything above 10240."""
        resource = FakeResource(256, FakeResource.RLIM_INFINITY, refuse_above=10240)
        self.assertEqual(fd_limit.raise_open_file_limit(resource), 10240)
        self.assertEqual(resource.attempts, [65536, 10240])
        self.assertEqual(resource.limits, (10240, FakeResource.RLIM_INFINITY))  # hard untouched

    def test_a_finite_hard_limit_is_the_ceiling(self):
        resource = FakeResource(1024, 524288)
        self.assertEqual(fd_limit.raise_open_file_limit(resource), 65536)
        small = FakeResource(256, 2048)
        self.assertEqual(fd_limit.raise_open_file_limit(small), 2048)
        self.assertEqual(small.attempts, [2048])

    def test_a_limit_that_is_already_high_is_left_alone(self):
        resource = FakeResource(1048576, 1048576)
        with self.assertNoLogs("partyline.fd_limit", "WARNING"):
            self.assertEqual(fd_limit.raise_open_file_limit(resource), 1048576)
        self.assertEqual(resource.attempts, [])

    def test_a_host_that_refuses_every_raise_gets_a_warning_with_the_remedy(self):
        resource = FakeResource(256, FakeResource.RLIM_INFINITY, refuse_above=0)
        with self.assertLogs("partyline.fd_limit", "WARNING") as logs:
            self.assertEqual(fd_limit.raise_open_file_limit(resource), 256)
        self.assertEqual(resource.attempts, [65536, 10240, 4096])
        self.assertIn("ulimit -n 10240", logs.output[0])

    def test_a_platform_without_the_resource_module_has_nothing_to_raise(self):
        with patch.dict(sys.modules, {"resource": None}):
            self.assertIsNone(fd_limit.raise_open_file_limit())

    @unittest.skipIf(sys.platform == "win32", "no descriptor limit of this kind")
    def test_the_real_limit_never_goes_down(self):
        import resource

        before = resource.getrlimit(resource.RLIMIT_NOFILE)
        self.addCleanup(resource.setrlimit, resource.RLIMIT_NOFILE, before)
        after = fd_limit.raise_open_file_limit()
        self.assertGreaterEqual(after, before[0])
        self.assertEqual(resource.getrlimit(resource.RLIMIT_NOFILE)[1], before[1])


if __name__ == "__main__":
    unittest.main()
