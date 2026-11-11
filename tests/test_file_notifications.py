"""Native readiness, bounded watch sets and directory creation, with no timed waits."""

import ctypes
import errno
from pathlib import Path
import os
import struct
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from partyline.file_events import FileEvents
from partyline.file_notify_linux import LinuxNotify
from partyline.file_watch_paths import normalize, plan


class QuietLoop:
    def __init__(self):
        self.readers = {}
        self.callbacks = []
        self.time = 0

    def add_reader(self, descriptor, callback):
        self.readers[descriptor] = callback

    def remove_reader(self, descriptor):
        del self.readers[descriptor]

    def advance(self, seconds):
        self.time += seconds
        for callback in self.callbacks:
            callback()


@unittest.skipUnless(sys.platform == 'linux', 'native Linux descriptor')
class NativeLinuxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.loop = QuietLoop()

    def backend(self, loop, changed, failed):
        return LinuxNotify(self.loop, changed, failed)

    async def test_database_in_home_registers_one_watch_despite_nested_directories(self):
        for n in range(100):
            (self.root / f'project-{n}' / 'node_modules' / 'deep').mkdir(parents=True)
        async with FileEvents(self.root / 'partyline.db', backend=self.backend) as events:
            lines = Path(f'/proc/self/fdinfo/{events.watcher.fd}').read_text().splitlines()
            self.assertEqual(sum(line.startswith('inotify wd:') for line in lines), 1)
            self.assertEqual(set(events.watcher.watches), {self.root})

    async def test_reader_registration_failure_closes_the_native_descriptor(self):
        loop = Mock(add_reader=Mock(side_effect=OSError('no reader')))
        with patch('partyline.file_notify_linux.os.close', wraps=os.close) as close:
            with self.assertRaisesRegex(OSError, 'no reader'):
                LinuxNotify(loop, Mock(), Mock())
            close.assert_called_once()

    async def test_idle_virtual_hour_schedules_no_work_and_reads_nothing(self):
        with patch('partyline.file_notify_linux.os.read', wraps=os.read) as read:
            async with FileEvents(self.root / 'db', backend=self.backend) as events:
                for _ in range(60):
                    self.loop.advance(60)
                self.assertEqual(events.changes.version, 0)
                self.assertEqual(self.loop.callbacks, [])
                self.assertEqual(len(self.loop.readers), 1)
                read.assert_not_called()
            self.assertEqual(self.loop.readers, {})

    async def test_missing_parents_rearm_one_level_down_on_creation(self):
        target = self.root / 'first' / 'second' / 'transcript.jsonl'
        async with FileEvents(target, backend=self.backend) as events:
            self.assertEqual(set(events.watcher.watches), {self.root})
            (self.root / 'first').mkdir()
            events.watcher.readable()
            await events.wait()
            self.assertEqual(set(events.watcher.watches), {self.root / 'first'})
            target.parent.mkdir()
            events.watcher.readable()
            await events.wait()
            self.assertEqual(set(events.watcher.watches), {target.parent})
            target.write_text('created before the consumer scans')
            events.watcher.readable()
            await events.wait()
            self.assertEqual(target.read_text(), 'created before the consumer scans')

    async def test_parent_removed_between_stat_and_add_rearms_ancestor_then_recreation(self):
        target = self.root / 'session' / 'transcript'
        target.parent.mkdir()
        api = ctypes.CDLL(None, use_errno=True)
        native_add = api.inotify_add_watch
        native_add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        removed = False

        def delete_before_add(descriptor, raw, mask):
            nonlocal removed
            if os.fsdecode(raw) == str(target.parent) and not removed:
                target.parent.rmdir()  # LinuxNotify.add already completed path.stat().
                removed = True
                ctypes.set_errno(errno.ENOENT)
                return -1
            return native_add(descriptor, raw, mask)

        api.inotify_add_watch = Mock(side_effect=delete_before_add)

        def factory(_, changed, failed):
            return LinuxNotify(self.loop, changed, failed, api)

        async with FileEvents(target, backend=factory) as events:
            self.assertTrue(removed)
            self.assertEqual(set(events.watcher.watches), {self.root})
            target.parent.mkdir()
            target.write_text('first record')
            events.watcher.readable()
            self.assertGreater(events.changes.version, 0)
            await events.wait()
            self.assertEqual(set(events.watcher.watches), {target.parent})
            target.write_text('later record')
            observed = events.changes.version
            events.watcher.readable()
            self.assertGreater(events.changes.version, observed)
            await events.wait()
            self.assertEqual(target.read_text(), 'later record')

    async def test_whole_missing_tree_created_before_notification_is_not_lost(self):
        target = self.root / 'one' / 'two' / 'transcript'
        async with FileEvents(target, backend=self.backend) as events:
            target.parent.mkdir(parents=True)
            target.write_text('already complete')
            events.watcher.readable()
            await events.wait()
            self.assertEqual(set(events.watcher.watches), {target.parent})
            self.assertEqual(target.read_text(), 'already complete')

    async def test_rotation_unlink_and_recreate_keep_directory_registration(self):
        target = self.root / 'transcript.jsonl'
        target.write_text('old')
        async with FileEvents(target, backend=self.backend) as events:
            target.rename(target.with_suffix('.old'))
            target.write_text('new')
            events.watcher.readable()
            await events.wait()
            target.unlink()
            events.watcher.readable()
            await events.wait()
            target.write_text('replacement')
            events.watcher.readable()
            await events.wait()
            self.assertEqual(len(events.watcher.watches), 1)

    async def test_directory_itself_can_be_removed_and_replaced(self):
        directory = self.root / 'session'
        directory.mkdir()
        async with FileEvents(directory / 'transcript', backend=self.backend) as events:
            directory.rmdir()
            events.watcher.readable()
            await events.wait()
            self.assertEqual(set(events.watcher.watches), {self.root})
            directory.mkdir()
            events.watcher.readable()
            await events.wait()
            self.assertEqual(set(events.watcher.watches), {directory})

    async def test_shallow_wildcards_follow_only_declared_depth(self):
        transcript = self.root / 'projects' / 'one' / 'session.jsonl'
        ignored = transcript.parent / 'node_modules' / 'deep'
        ignored.mkdir(parents=True)
        async with FileEvents(self.root / 'projects' / '*' / 'session.jsonl',
                              backend=self.backend) as events:
            self.assertEqual(set(events.watcher.watches), {transcript.parent.parent, transcript.parent})
            transcript.write_text('structured record')
            events.watcher.readable()
            await events.wait()
            self.assertFalse(any('node_modules' in path.parts for path in events.watcher.watches))

    async def test_kernel_overflow_fails_consumers_instead_of_silent_loss(self):
        async with FileEvents(self.root / 'file', backend=self.backend) as events:
            overflow = struct.pack('iIII', -1, 0x4000, 0, 0)
            with patch('partyline.file_notify_linux.os.read', return_value=overflow):
                events.watcher.readable()
            with self.assertRaisesRegex(OSError, 'overflow'):
                await events.wait()


class PlanningTests(unittest.IsolatedAsyncioTestCase):
    async def test_directory_self_events_absent_adds_only_one_shallow_guard(self):
        watcher = Mock(add=Mock(), retain=Mock(), close=AsyncMock(),
                       file_vnodes=False, directory_self_events=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async with FileEvents(root / 'file', backend=lambda *a: watcher):
                self.assertEqual({call.args[0] for call in watcher.add.call_args_list}, {root, root.parent})

    async def test_registration_failure_closes_partial_watcher(self):
        watcher = Mock(add=Mock(side_effect=PermissionError('denied')), close=AsyncMock())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PermissionError):
                async with FileEvents(Path(directory) / 'file', backend=lambda *a: watcher):
                    self.fail('entered without observation')
        watcher.close.assert_awaited_once()

    def test_recursive_glob_is_refused_and_watch_budget_is_bounded(self):
        with self.assertRaisesRegex(ValueError, 'bounded'):
            normalize('/home/user/**/transcript')
        with tempfile.TemporaryDirectory() as directory:
            for n in range(4):
                (Path(directory) / str(n)).mkdir()
            with patch('partyline.file_watch_paths.MAX_WATCHES', 3):
                with self.assertRaisesRegex(OSError, '4096'):
                    plan([Path(directory) / '*' / 'file'], Mock())

    async def test_late_native_callback_after_close_is_ignored(self):
        watcher = Mock(add=Mock(), retain=Mock(), close=AsyncMock(),
                       file_vnodes=False, directory_self_events=True)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'file'
            async with FileEvents(target, backend=lambda *a: watcher) as events:
                pass
            events.changed({target})
            events.failed(OSError('late completion'))
            self.assertEqual(events.changes.version, 0)
