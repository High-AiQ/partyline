"""Shallow native filesystem events, armed before authoritative state scans."""

import asyncio
from contextlib import asynccontextmanager
import sys
import weakref

from .file_watch_paths import normalize, plan, relevant


def native_notify(loop, changed, failed):
    if sys.platform == 'linux':
        from .file_notify_linux import LinuxNotify
        return LinuxNotify(loop, changed, failed)
    if sys.platform == 'win32':
        from .file_notify_windows import WindowsNotify
        return WindowsNotify(loop, changed, failed)
    from .file_notify_kqueue import KqueueNotify
    return KqueueNotify(loop, changed, failed)


class Changes:
    """A broadcast pulse with per-task cursors, so concurrent consumers lose no wake."""

    def __init__(self):
        self.error = None
        self.version = 0
        self.event = asyncio.Event()
        self.cursors = weakref.WeakKeyDictionary()

    def notify(self, error=None):
        if error is not None:
            self.error = error
        self.version += 1
        self.event.set()

    async def wait_after(self, observed):
        while observed == self.version:
            self.event.clear()
            await self.event.wait()
        if self.error is not None:
            raise self.error

    async def wait(self, owner=None):
        task = owner or asyncio.current_task()
        while self.cursors.get(task, 0) == self.version:
            self.event.clear()
            await self.event.wait()
        self.cursors[task] = self.version
        if self.error is not None:
            raise self.error


class FileEvents:
    def __init__(self, *paths, changes=None, backend=None):
        self.paths = tuple(normalize(path) for path in paths)
        self.changes = changes or Changes()
        self.backend = backend or native_notify
        self.closed = False

    def refresh(self):
        self.watcher.retain(plan(self.paths, self.watcher.add,
                                 getattr(self.watcher, 'file_vnodes', False),
                                 getattr(self.watcher, 'directory_self_events', True)))

    def changed(self, paths):
        if self.closed or not any(relevant(spec, path) for spec in self.paths for path in paths):
            return
        try:
            self.refresh()
            self.changes.notify()
        except Exception as exc:
            self.failed(exc)

    def failed(self, error):
        if not self.closed:
            self.changes.notify(error)

    async def __aenter__(self):
        self.watcher = self.backend(asyncio.get_running_loop(), self.changed, self.failed)
        try:
            self.refresh()
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def wait(self, owner=None):
        await self.changes.wait(owner)

    async def __aexit__(self, *args):
        self.closed = True
        await self.watcher.close()


@asynccontextmanager
async def file_events(*paths):
    async with FileEvents(*paths) as events:
        yield events
