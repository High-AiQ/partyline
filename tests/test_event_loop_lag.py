import asyncio
import logging
import os
import time
import unittest
from unittest.mock import patch

from partyline.event_loop_lag import _setting, monitor


class EventLoopLagTest(unittest.IsolatedAsyncioTestCase):
    def test_settings_reject_invalid_values(self):
        with patch.dict(os.environ, {'TEST_LAG': 'nan'}):
            self.assertEqual(_setting('TEST_LAG', 0.1, 0), 0.1)
        with patch.dict(os.environ, {'TEST_LAG': 'bad'}):
            self.assertEqual(_setting('TEST_LAG', 0.1, 0), 0.1)
        with patch.dict(os.environ, {'TEST_LAG': '-1'}):
            self.assertEqual(_setting('TEST_LAG', 0.1, 0), 0.1)

    async def test_stall_warns_and_is_rate_limited(self):
        settings = {'PARTYLINE_LOOP_LAG_INTERVAL': '0.01',
                    'PARTYLINE_LOOP_LAG_THRESHOLD': '0.005',
                    'PARTYLINE_LOOP_LAG_COOLDOWN': '10'}
        with patch.dict(os.environ, settings), self.assertLogs(
                'partyline.event_loop_lag', level=logging.WARNING) as logs:
            task = asyncio.create_task(monitor())
            await asyncio.sleep(0.005)
            time.sleep(0.03)
            await asyncio.sleep(0.015)
            time.sleep(0.03)
            await asyncio.sleep(0.015)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(len(logs.output), 1)
        self.assertIn('event loop lag', logs.output[0])
