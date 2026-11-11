"""Local input and retention events wake consumers without advancing a clock."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from partyline.file_events import Changes
from partyline import retention_events
from partyline_helper.capture_loop import capture
from tests.adapter_event_clock import FixtureFiles
from tests.screen_helper_fakes import checkpoint


class HelperEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_stop_wakes_capture_without_frame_deadline(self):
        request = {'share_id': 'share', 'max_fps': 30}
        inputs = asyncio.Queue()
        reading = asyncio.Event()
        changes = Changes()

        async def read(_):
            reading.set()
            return await inputs.get()

        session = SimpleNamespace(
            share=request, accepted=True, pending_id='share',
            control=SimpleNamespace(input_changes=changes, prompting=False, end=Mock()),
            terminal=SimpleNamespace(read=read), frame=AsyncMock(), send=AsyncMock(),
            sleep=lambda _: asyncio.Event().wait())
        task = asyncio.create_task(capture(session, request))
        try:
            await reading.wait()
            # A prompt's completed notification may coincide with an already-read line.
            inputs.put_nowait('s')
            changes.notify()
            await task
            self.assertIsNone(session.share)
            self.assertIsNone(session.pending_id)
            session.control.end.assert_called_once()
            session.send.assert_awaited_once_with('share_stopped', share_id='share', reason='local')
            session.frame.assert_awaited_once()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_retained_process_exit_notifies_maintenance(self):
        changes = Changes()
        exited = asyncio.Event()
        watching = asyncio.Event()

        async def process_exited(pid):
            self.assertEqual(pid, 123)
            watching.set()
            await exited.wait()

        class Files(FixtureFiles):
            async def wait(self, owner=None):
                await asyncio.Event().wait()

        with patch.object(retention_events, 'FileEvents', Files), \
                patch.object(retention_events, 'retained_jobs', side_effect=[{123}, set()]), \
                patch.object(retention_events, 'process_exited', process_exited):
            async with retention_events.retention_notifications(changes):
                await watching.wait()
                self.assertEqual(changes.version, 0)
                exited.set()
                await changes.wait()
                self.assertEqual(changes.version, 1)
                await checkpoint()

    def test_retention_only_observes_matching_process_identity(self):
        with TemporaryDirectory() as directory:
            registry = Path(directory) / '.pending-reaps'
            registry.mkdir()
            (registry / 'valid.json').write_text(json.dumps({
                'processes': {'1': 'same', '2': 'old', '3': None}}))
            (registry / 'bad.json').write_text('{')
            with patch.object(retention_events, 'base_dir', return_value=Path(directory)), \
                    patch.object(retention_events, 'process_identity', return_value='same'):
                self.assertEqual(retention_events.retained_jobs(), {1})
