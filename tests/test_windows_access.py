import unittest
from unittest.mock import MagicMock, patch

from partyline import windows_access as access


class WindowsAccessCheckTest(unittest.TestCase):
    def test_kernel_decision_is_distinct_from_api_failure(self):
        for permitted in (True, False):
            api = MagicMock()
            def native(*args, wanted=permitted):
                args[-1]._obj.value = wanted
                return 1
            api.AccessCheck.side_effect = native
            with patch.object(access.c, 'WinDLL', return_value=api, create=True):
                self.assertEqual(access.check(b'descriptor', 123, 2), permitted)

    def test_failure_or_unbounded_privilege_buffer_never_means_denied(self):
        for error, length in ((5, 1024), (122, 65537)):
            api = MagicMock()
            def native(*args, wanted=length):
                args[-3]._obj.value = wanted
                return 0
            api.AccessCheck.side_effect = native
            with patch.object(access.c, 'WinDLL', return_value=api, create=True), \
                 patch.object(access.c, 'get_last_error', return_value=error, create=True), \
                 patch.object(access.c, 'WinError', side_effect=lambda code: OSError(code), create=True):
                with self.assertRaises(OSError):
                    access.check(b'descriptor', 123, 2)

    def test_buffer_growth_gets_one_bounded_retry(self):
        api = MagicMock()
        calls = []
        def native(*args):
            calls.append(1)
            if len(calls) == 1:
                args[-3]._obj.value = 2048
                return 0
            args[-1]._obj.value = 1
            return 1
        api.AccessCheck.side_effect = native
        with patch.object(access.c, 'WinDLL', return_value=api, create=True), \
             patch.object(access.c, 'get_last_error', return_value=122, create=True):
            self.assertTrue(access.check(b'descriptor', 123, 2))
        self.assertEqual(len(calls), 2)
