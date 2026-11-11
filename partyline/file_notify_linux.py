"""One non-recursive inotify descriptor; idle work is owned by the kernel."""

import ctypes
import errno
import os
import struct

MASK = 0x2 | 0x4 | 0x8 | 0x40 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800
HEADER = struct.Struct('iIII')


class LinuxNotify:
    def __init__(self, loop, changed, failed, api=None):
        self.loop, self.changed, self.failed = loop, changed, failed
        self.api = api or ctypes.CDLL(None, use_errno=True)
        self.api.inotify_init1.argtypes = [ctypes.c_int]
        self.api.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.api.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self.fd = self.api.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), 'inotify_init1')
        self.watches = {}
        try:
            loop.add_reader(self.fd, self.readable)
        except BaseException:
            os.close(self.fd)
            raise

    def add(self, path):
        status = path.stat()
        identity = (status.st_dev, status.st_ino)
        existing = self.watches.get(path)
        if existing and existing[1] == identity:
            return
        if existing:
            self.remove(path)
        descriptor = self.api.inotify_add_watch(self.fd, os.fsencode(path), MASK)
        if descriptor < 0:
            error = ctypes.get_errno()
            if error == errno.ENOENT:
                raise FileNotFoundError(error, 'inotify_add_watch', str(path))
            raise OSError(error, f'inotify_add_watch: {path}')
        self.watches[path] = (descriptor, identity)

    def remove(self, path):
        descriptor, _ = self.watches.pop(path)
        if not any(watch == descriptor for watch, _ in self.watches.values()):
            self.api.inotify_rm_watch(self.fd, descriptor)

    def retain(self, paths):
        for path in self.watches.keys() - paths:
            self.remove(path)

    def readable(self):
        try:
            paths = set()
            # Drain only what the kernel has reported ready; no deadline/retry.
            while True:
                try:
                    data = os.read(self.fd, 65536)
                except BlockingIOError:
                    break
                if not data:
                    raise OSError('inotify descriptor closed unexpectedly')
                offset = 0
                while offset < len(data):
                    descriptor, mask, _, length = HEADER.unpack_from(data, offset)
                    raw = data[offset + HEADER.size:offset + HEADER.size + length]
                    name = os.fsdecode(raw.split(b'\0')[0])
                    offset += HEADER.size + length
                    if mask & 0x4000:
                        raise OSError('inotify event queue overflow; filesystem observation lost')
                    for directory, (watch, _) in list(self.watches.items()):
                        if watch == descriptor:
                            paths.add(directory / name if name else directory)
                            if mask & 0x8000:  # IN_IGNORED invalidates this registration
                                self.watches.pop(directory, None)
            if paths:
                self.changed(paths)
        except Exception as exc:
            self.failed(exc)

    async def close(self):
        self.loop.remove_reader(self.fd)
        os.close(self.fd)
        self.watches.clear()
