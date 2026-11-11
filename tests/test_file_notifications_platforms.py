"""Fake native readiness/completion sources exercise both platform lifecycles."""

import asyncio
import ctypes
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from partyline.file_events import FileEvents
from partyline.file_notify_kqueue import KqueueNotify
from partyline.file_notify_windows import WindowsNotify
from tests.test_file_notifications import QuietLoop


class FakeKqueue:
    def __init__(self):
        self.events = []
        self.registrations = []
        self.close = Mock()

    def fileno(self):
        return 5000

    def control(self, changes, count, timeout=None):
        self.registrations.extend(changes)
        events, self.events = self.events[:count], self.events[count:]
        return events


class KqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_file_vnode_sees_appends_without_recursive_directory_fds(self):
        queue = FakeKqueue()
        api = SimpleNamespace(kqueue=lambda: queue, kevent=lambda fd, **kw: SimpleNamespace(ident=fd, **kw),
            KQ_NOTE_DELETE=1, KQ_NOTE_WRITE=2, KQ_NOTE_EXTEND=4, KQ_NOTE_ATTRIB=8,
            KQ_NOTE_RENAME=16, KQ_NOTE_REVOKE=32, KQ_FILTER_VNODE=1,
            KQ_EV_ADD=1, KQ_EV_ENABLE=2, KQ_EV_CLEAR=4, KQ_EV_ERROR=8)
        loop = QuietLoop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'db'
            target.write_text('before')
            (root / 'node_modules' / 'nested').mkdir(parents=True)
            def factory(_, changed, failed):
                return KqueueNotify(loop, changed, failed, api)
            async with FileEvents(target, backend=factory) as events:
                self.assertEqual(set(events.watcher.watches), {root, target})
                loop.advance(3600)
                self.assertEqual(events.changes.version, 0)
                descriptor = events.watcher.watches[target][0]
                target.write_text('after append')
                queue.events = [SimpleNamespace(ident=descriptor, flags=0)]
                events.watcher.readable()
                await events.wait()
                target.unlink()
                queue.events = [SimpleNamespace(ident=descriptor, flags=0)]
                events.watcher.readable()
                await events.wait()
                self.assertEqual(set(events.watcher.watches), {root})
                target.write_text('replaced')
                queue.events = [SimpleNamespace(ident=events.watcher.watches[root][0], flags=0)]
                events.watcher.readable()
                await events.wait()
                self.assertIn(target, events.watcher.watches)
            queue.close.assert_called_once()
            self.assertEqual(loop.readers, {})


class FakeWindowsKernel:
    def __init__(self, loop):
        self.loop = loop
        self.waiting = asyncio.Queue()
        self.reads = self.waits = self.cancels = 0
        self.handles_closed, self.records, self.events = [], {}, {}
        self.handle = 40

    def CreateFileW(self, path, *args):
        self.handle += 1
        self.records[self.handle] = {'path': path, 'count': 0}
        return self.handle

    def CreateEventW(self, *args):
        self.handle += 1
        self.events[self.handle] = threading.Event()
        return self.handle

    def ResetEvent(self, event):
        self.events[event].clear()

    def ReadDirectoryChangesW(self, handle, buffer, size, subtree, mask, count, overlap, callback):
        assert subtree is False
        self.records[handle].update(buffer=buffer, event=overlap._obj.event)
        self.reads += 1
        return True

    def WaitForSingleObject(self, event, timeout):
        assert timeout == 0xffffffff
        self.waits += 1
        self.loop.call_soon_threadsafe(self.waiting.put_nowait, None)
        self.events[event].wait()
        return 0

    def GetOverlappedResult(self, handle, overlap, count, wait):
        count._obj.value = self.records[handle]['count']
        return True

    def CancelIoEx(self, handle, overlap):
        self.cancels += 1
        self.events[self.records[handle]['event']].set()
        return True

    def CloseHandle(self, handle):
        self.handles_closed.append(handle)

    def deliver(self, directory, name):
        record = next(item for item in self.records.values() if item['path'] == str(directory))
        encoded = name.encode('utf-16-le')
        data = struct.pack('III', 0, 3, len(encoded)) + encoded
        ctypes.memmove(record['buffer'], data, len(data))
        record['count'] = len(data)
        self.events[record['event']].set()


class WindowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_start_failure_cancels_pending_io_before_releasing_handles(self):
        api = FakeWindowsKernel(asyncio.get_running_loop())
        with tempfile.TemporaryDirectory() as directory:
            def factory(loop, changed, failed):
                return WindowsNotify(loop, changed, failed, api)
            with patch('partyline.file_notify_windows.threading.Thread.start',
                       side_effect=OSError('no threads')):
                with self.assertRaisesRegex(OSError, 'no threads'):
                    async with FileEvents(Path(directory) / 'file', backend=factory):
                        self.fail('entered without a notification source')
            self.assertEqual(api.cancels, 1)
            self.assertCountEqual(api.handles_closed, [41, 42])

    async def test_shallow_blocking_read_idle_then_delivery_then_cancelled_shutdown(self):
        api = FakeWindowsKernel(asyncio.get_running_loop())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'transcript'
            def factory(loop, changed, failed):
                return WindowsNotify(loop, changed, failed, api)
            async with FileEvents(target, backend=factory) as events:
                await api.waiting.get()
                await api.waiting.get()  # parent guard observes renames of the watched directory itself
                for _ in range(10):
                    await asyncio.sleep(0)  # only drain ready callbacks; no real interval
                self.assertEqual((api.waits, api.reads, events.changes.version), (2, 2, 0))
                api.deliver(target.parent, 'transcript')
                await events.wait()
                await api.waiting.get()
                self.assertEqual(api.reads, 3)
            self.assertEqual(api.cancels, 2)
            self.assertCountEqual(api.handles_closed, [41, 42, 43, 44])
            self.assertTrue(all(task.done() for task in events.watcher.retired))
