from types import SimpleNamespace
import unittest
from unittest.mock import patch

from partyline import windows_platform


class WindowsPlatformTest(unittest.TestCase):
    def test_old_windows_and_missing_dependency_fail_with_remedy(self):
        with patch.object(windows_platform.sys, 'getwindowsversion', create=True) as version, \
             patch.object(windows_platform.importlib.util, 'find_spec') as dependency:
            version.return_value = SimpleNamespace(major=10, build=17134)
            self.assertIn('17763', windows_platform.available()[1])
            dependency.assert_not_called()
            version.return_value = SimpleNamespace(major=10, build=19045)
            dependency.return_value = None
            self.assertIn('uv sync --locked', windows_platform.available()[1])
            dependency.return_value = object()
            self.assertEqual(windows_platform.available(), (True, ''))
