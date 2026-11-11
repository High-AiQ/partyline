"""Windows resource notifications alternate low/high without timer reads."""

import unittest
from unittest.mock import Mock, patch

from partyline.memory_events_windows import WindowsMemoryEvents


class WindowsMemoryEventsTest(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_opposite_state_and_stops(self):
        kernel = Mock()
        kernel.CreateMemoryResourceNotification.side_effect = [10, 11]
        kernel.CreateEventW.return_value = 12
        kernel.WaitForMultipleObjects.side_effect = [0, 0, 1]
        loop, notify = Mock(), Mock()
        thread = Mock()
        with patch("partyline.memory_events_windows.threading.Thread", return_value=thread):
            watcher = WindowsMemoryEvents(loop, notify, kernel)
        watcher._wait()
        self.assertEqual(loop.call_soon_threadsafe.call_args_list[0].args, (notify, None, True))
        self.assertEqual(loop.call_soon_threadsafe.call_args_list[1].args, (notify, None, False))
        self.assertEqual(kernel.WaitForMultipleObjects.call_count, 3)
        await watcher.close()
        kernel.SetEvent.assert_called_once_with(12)
        thread.join.assert_called_once()
        self.assertEqual(kernel.CloseHandle.call_count, 3)

    async def test_partial_initialization_closes_handles(self):
        kernel = Mock()
        kernel.CreateMemoryResourceNotification.side_effect = [10, None]
        with self.assertRaises(OSError):
            WindowsMemoryEvents(Mock(), Mock(), kernel)
        kernel.CloseHandle.assert_called_once_with(10)
