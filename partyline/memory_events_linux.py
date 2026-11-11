"""Linux PSI and cgroup-v2 memory event notifications."""

import ctypes
import logging
import os
from pathlib import Path
import select
import struct

logger = logging.getLogger(__name__)
TRIGGER = b"some 200000 2000000\n"
EVENT_KEYS = ("high", "max", "oom", "oom_kill")
IN_MODIFY = 0x2
IN_DELETE_SELF = 0x400
IN_MOVE_SELF = 0x800
IN_Q_OVERFLOW = 0x4000
IN_IGNORED = 0x8000
HEADER = struct.Struct("iIII")


def open_psi(path):
    """Arm one PSI trigger; its fd must stay open while it is registered."""
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        os.write(fd, TRIGGER)
    except BaseException:
        os.close(fd)
        raise
    return fd


def scope_path(pid):
    try:
        lines = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
        relative = next(line.split("::", 1)[1] for line in lines if line.startswith("0::"))
        return str(Path("/sys/fs/cgroup") / relative.lstrip("/"))
    except (OSError, StopIteration):
        return None


def read_counters(path):
    try:
        values = dict(line.split() for line in Path(path).read_text().splitlines())
        return {key: int(values.get(key, 0)) for key in EVENT_KEYS}
    except (OSError, ValueError):
        return {}


class LinuxMemoryEvents:
    """Attach PSI trigger fds to epoll and watch each scope's memory.events."""

    def __init__(self, loop, notify):
        self.loop, self.notify = loop, notify
        self.poller = select.epoll()
        self.pressure = {}  # fd -> scope root, or None for host pressure
        self.scopes = {}  # scope root -> attachment ids
        self.scope_fds = {}
        self.watches = {}  # inotify watch descriptor -> (scope root, counters)
        self.api = ctypes.CDLL(None, use_errno=True)
        self.api.inotify_init1.argtypes = [ctypes.c_int]
        self.api.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.api.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self.inotify = self.api.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        loop.add_reader(self.poller.fileno(), self._pressure_ready)
        if self.inotify >= 0:
            loop.add_reader(self.inotify, self._events_ready)
        self._add_pressure("/proc/pressure/memory", None)

    def _add_pressure(self, path, scope):
        try:
            fd = open_psi(path)
            try:
                self.poller.register(fd, select.EPOLLPRI | select.EPOLLERR)
            except BaseException:
                os.close(fd)
                raise
        except OSError as exc:
            logger.debug("memory PSI unavailable for %s: %s", path, exc)
            return None
        self.pressure[fd] = scope
        return fd

    def sync(self, attachments):
        """Replace the attachment-to-cgroup mapping after lifecycle changes."""
        scopes = {}
        for ident, root in attachments.items():
            if root:
                scopes.setdefault(root, set()).add(ident)
        for root in self.scopes.keys() - scopes.keys():
            self._remove_scope(root)
        for root in scopes:
            if self.scope_fds.get(root) is None:
                self.scope_fds[root] = self._add_pressure(f"{root}/memory.pressure", root)
            if self.inotify >= 0 and not any(watched == root for watched, _ in self.watches.values()):
                path = f"{root}/memory.events"
                before = read_counters(path)
                wd = self.api.inotify_add_watch(self.inotify, os.fsencode(path),
                                                IN_MODIFY | IN_DELETE_SELF | IN_MOVE_SELF)
                if wd >= 0:
                    after = read_counters(path)
                    self.watches[wd] = (root, after or before)
                    if before and after and any(after[key] > before.get(key, 0) for key in EVENT_KEYS):
                        warning = any(after[key] > before.get(key, 0) for key in ("high", "max"))
                        self.notify(scopes[root], warning)
        self.scopes = scopes

    def _remove_scope(self, root):
        fd = self.scope_fds.pop(root, None)
        if fd is not None:
            self.poller.unregister(fd)
            self.pressure.pop(fd, None)
            os.close(fd)
        for wd, (watched, _) in list(self.watches.items()):
            if watched == root:
                self.api.inotify_rm_watch(self.inotify, wd)
                self.watches.pop(wd, None)

    def _pressure_ready(self):
        for fd, mask in self.poller.poll(0):
            if fd not in self.pressure:
                continue
            root = self.pressure[fd]
            if mask & select.EPOLLPRI:
                self.notify(None if root is None else set(self.scopes.get(root, ())), True)
            elif mask & (select.EPOLLERR | select.EPOLLHUP):
                self.poller.unregister(fd)
                self.pressure.pop(fd, None)
                if root is not None:
                    self.scope_fds[root] = None
                os.close(fd)

    def _events_ready(self):
        try:
            data = os.read(self.inotify, 65536)
        except BlockingIOError:
            return
        offset = 0
        while offset + HEADER.size <= len(data):
            wd, mask, _, length = HEADER.unpack_from(data, offset)
            offset += HEADER.size + length
            if mask & IN_Q_OVERFLOW:
                for watch in list(self.watches):
                    self._read_watch(watch)
                continue
            watched = self.watches.get(wd)
            if watched is None:
                continue
            if mask & IN_MODIFY:
                self._read_watch(wd)
            if mask & (IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED):
                self.watches.pop(wd, None)

    def _read_watch(self, wd):
        root, before = self.watches[wd]
        after = read_counters(f"{root}/memory.events")
        if after and any(after[key] > before.get(key, 0) for key in EVENT_KEYS):
            warning = any(after[key] > before.get(key, 0) for key in ("high", "max"))
            self.notify(set(self.scopes.get(root, ())), warning)
        if after:
            self.watches[wd] = (root, after)

    def close(self):
        for root in list(self.scopes):
            self._remove_scope(root)
        self.loop.remove_reader(self.poller.fileno())
        for fd in list(self.pressure):
            self.poller.unregister(fd)
            os.close(fd)
        self.pressure.clear()
        self.poller.close()
        if self.inotify >= 0:
            self.loop.remove_reader(self.inotify)
            os.close(self.inotify)
