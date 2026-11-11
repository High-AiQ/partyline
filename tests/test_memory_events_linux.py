"""PSI and cgroup notifications, without waiting on the real kernel."""

import asyncio
import errno
import os
import select
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from partyline import memory_events_linux as events


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux event source only")
class LinuxMemoryEventsTest(unittest.TestCase):
    def test_failed_registration_closes_allocated_descriptors(self):
        inotify_fd, writer = os.pipe()
        self.addCleanup(os.close, writer)
        poller = Mock()
        poller.fileno.return_value = 100
        api = Mock()
        api.inotify_init1.return_value = inotify_fd
        loop = Mock()
        loop.add_reader.side_effect = OSError("no selector")
        with patch.object(events.ctypes, "CDLL", return_value=api), \
                patch.object(events.select, "epoll", return_value=poller):
            with self.assertRaises(OSError):
                events.LinuxMemoryEvents(loop, Mock())
        with self.assertRaises(OSError):
            os.fstat(inotify_fd)
        poller.close.assert_called_once()

    def test_registers_and_removes_scope_fds_and_watches(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "memory.events"
            path.write_text("high 0\nmax 0\noom 0\noom_kill 0\n")
            global_fd, global_write = os.pipe()
            scope_fd, scope_write = os.pipe()
            inotify_fd, inotify_write = os.pipe()
            self.addCleanup(os.close, global_write)
            self.addCleanup(os.close, scope_write)
            self.addCleanup(os.close, inotify_write)
            poller = Mock()
            poller.fileno.return_value = 100
            api = Mock()
            api.inotify_init1.return_value = inotify_fd
            api.inotify_add_watch.return_value = 7
            loop = Mock()
            with patch.object(events.ctypes, "CDLL", return_value=api), \
                    patch.object(events.select, "epoll", return_value=poller), \
                    patch.object(events, "open_psi", side_effect=[global_fd, scope_fd]):
                watcher = events.LinuxMemoryEvents(loop, Mock())
                watcher.sync({"worker": root})
                self.assertEqual(watcher.scopes[root], {"worker"})
                self.assertIn(7, watcher.watches)
                watcher.sync({})
                api.inotify_rm_watch.assert_called_once_with(inotify_fd, 7)
                watcher.close()
            self.assertEqual(loop.remove_reader.call_count, 2)

    def test_fake_psi_fd_delivers_host_and_scope_pressure(self):
        watcher = events.LinuxMemoryEvents.__new__(events.LinuxMemoryEvents)
        watcher.poller = Mock()
        watcher.poller.poll.return_value = [(11, select.EPOLLPRI), (12, select.EPOLLPRI)]
        watcher.pressure = {11: None, 12: "/scope"}
        watcher.scopes = {"/scope": {"worker"}}
        watcher.notify = Mock()
        watcher._pressure_ready()
        self.assertEqual(watcher.notify.call_args_list[0].args, (None, True))
        self.assertEqual(watcher.notify.call_args_list[1].args, ({"worker"}, True))
        watcher.poller.poll.assert_called_once_with(0)

    def test_fake_memory_events_change_warns_only_for_high_or_max(self):
        watcher = events.LinuxMemoryEvents.__new__(events.LinuxMemoryEvents)
        watcher.inotify = 9
        watcher.watches = {7: ("/scope", {key: 0 for key in events.EVENT_KEYS})}
        watcher.scopes = {"/scope": {"worker"}}
        watcher.notify = Mock()
        message = events.HEADER.pack(7, events.IN_MODIFY, 0, 0)
        with patch.object(events.os, "read", return_value=message), \
                patch.object(events, "read_counters", return_value={"high": 1, "max": 0,
                                                                   "oom": 0, "oom_kill": 0}):
            watcher._events_ready()
        watcher.notify.assert_called_once_with({"worker"}, True)

    def test_inotify_overflow_reads_registered_counters(self):
        watcher = events.LinuxMemoryEvents.__new__(events.LinuxMemoryEvents)
        watcher.inotify = 9
        watcher.watches = {7: ("/scope", {key: 0 for key in events.EVENT_KEYS})}
        watcher.scopes = {"/scope": {"worker"}}
        watcher.notify = Mock()
        message = events.HEADER.pack(-1, events.IN_Q_OVERFLOW, 0, 0)
        with patch.object(events.os, "read", return_value=message), \
                patch.object(events, "read_counters", return_value={"high": 0, "max": 0,
                                                                   "oom": 1, "oom_kill": 0}):
            watcher._events_ready()
        watcher.notify.assert_called_once_with({"worker"}, False)

    def test_real_psi_trigger_registers_when_available(self):
        try:
            fd = events.open_psi("/proc/pressure/memory")
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM, errno.ENOENT, errno.EROFS, errno.EINVAL):
                self.skipTest(f"PSI trigger unavailable: {exc}")
            raise
        try:
            poller = select.poll()
            poller.register(fd, select.POLLPRI)
            poller.unregister(fd)
        finally:
            os.close(fd)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux event source only")
class LinuxSelectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_selector_registration_and_close(self):
        watcher = events.LinuxMemoryEvents(asyncio.get_running_loop(), Mock())
        watcher.close()
