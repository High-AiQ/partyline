"""Container lifetimes schedule one deadline, without periodic reads."""

import asyncio
import unittest
from unittest.mock import Mock, patch

from partyline.docker_lifetime import LifetimeDeadlines, overdue


class LifetimeDeadlinesTest(unittest.IsolatedAsyncioTestCase):
    async def test_arm_replace_fire_and_cancel(self):
        deadlines = LifetimeDeadlines()
        callback = Mock()
        handles = []

        def call_at(when, fire):
            handle = Mock()
            handles.append((when, fire, handle))
            return handle

        container = {"id": "one", "state": "running", "managed": True,
                     "max_seconds": 30, "started_at": 100}
        loop = asyncio.get_running_loop()
        with patch.object(loop, "time", return_value=10), patch.object(loop, "call_at", side_effect=call_at):
            deadlines.update([container], 60, callback, now=110)
            self.assertEqual(handles[0][0], 30)
            deadlines.update([container], 60, callback, now=111)
            self.assertEqual(len(handles), 1)
            container["started_at"] = 120
            deadlines.update([container], 60, callback, now=121)
            handles[0][2].cancel.assert_called_once()
            handles[1][1]()
            callback.assert_called_once()
            self.assertEqual(deadlines.handles, {})
            deadlines.update([container], 60, callback, now=122)
            container["state"] = "exited"
            deadlines.update([container], 60, callback, now=123)
            handles[2][2].cancel.assert_called_once()

    async def test_expired_is_enforced_now_and_never_rearmed(self):
        container = {"id": "one", "state": "running", "managed": True,
                     "max_seconds": 30, "started_at": 100}
        deadlines = LifetimeDeadlines()
        self.assertEqual(overdue([container], 130), [container])
        deadlines.update([container], 60, Mock(), now=130)
        self.assertEqual(deadlines.handles, {})

    async def test_close_cancels_pending_deadlines(self):
        deadlines = LifetimeDeadlines()
        handle = Mock()
        deadlines.handles["one"] = (100, handle)
        deadlines.close()
        handle.cancel.assert_called_once()
        self.assertEqual(deadlines.handles, {})
