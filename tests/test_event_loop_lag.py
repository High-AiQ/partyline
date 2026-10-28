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

    async def test_warning_names_slowest_overlapping_tick(self):
        from partyline.periodic_timing import tick

        settings = {'PARTYLINE_LOOP_LAG_INTERVAL': '0.01',
                    'PARTYLINE_LOOP_LAG_THRESHOLD': '0.005',
                    'PARTYLINE_LOOP_LAG_COOLDOWN': '10'}
        with patch.dict(os.environ, settings), self.assertLogs(
                'partyline.event_loop_lag', level=logging.WARNING) as logs:
            monitor_task = asyncio.create_task(monitor())
            await asyncio.sleep(0.005)
            with tick('test job'):
                time.sleep(0.03)
            await asyncio.sleep(0.015)
            monitor_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await monitor_task
        self.assertIn('periodic job test job', logs.output[0])

    def test_timer_reports_active_completed_and_no_overlap(self):
        from partyline.periodic_timing import slowest, tick

        now = time.monotonic()
        self.assertIsNone(slowest(now + 100, now + 101))
        with tick('active job'):
            self.assertEqual(slowest(now, time.monotonic())[0], 'active job')
        self.assertEqual(slowest(now, time.monotonic())[0], 'active job')

    async def test_watchdog_samples_blocked_loop_without_values_and_stops(self):
        import threading

        settings = {'PARTYLINE_LOOP_LAG_INTERVAL': '0.01',
                    'PARTYLINE_LOOP_WATCHDOG_THRESHOLD': '0.03',
                    'PARTYLINE_LOOP_WATCHDOG_INTERVAL': '0.01',
                    'PARTYLINE_LOOP_WATCHDOG_COOLDOWN': '5'}

        async def deliberately_blocking_coroutine():
            secret_value = 'token-must-not-appear-in-the-log'
            time.sleep(0.12)
            return secret_value

        with patch.dict(os.environ, settings), self.assertLogs(
                'partyline.loop_watchdog', level=logging.WARNING) as logs:
            running = asyncio.create_task(monitor())
            await asyncio.sleep(0.02)
            await deliberately_blocking_coroutine()
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
        self.assertEqual(len(logs.output), 1)
        self.assertIn('deliberately_blocking_coroutine', logs.output[0])
        self.assertNotIn('token-must-not-appear-in-the-log', logs.output[0])
        self.assertFalse(any(t.name == 'event-loop-watchdog' for t in threading.enumerate()))
