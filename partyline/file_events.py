"""Shallow native filesystem events, armed before authoritative state scans."""

import asyncio
from contextlib import asynccontextmanager
import errno
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


def descriptors_exhausted(error):
    """Whether this process or this host ran out of file descriptors (and nothing else)."""
    return isinstance(error, OSError) and error.errno in (errno.EMFILE, errno.ENFILE)


class Changes:
    """A broadcast pulse with per-task cursors, so concurrent consumers lose no wake."""

    def __init__(self):
        self.error = None
        self.version = 0
        self.event = asyncio.Event()
        self.cursors = weakref.WeakKeyDictionary()
        self.retries = []  # watches that ran out of descriptors: any wake is a reason to retry

    def notify(self, error=None, skip=None):
        if error is not None:
            self.error = error
        for starved in list(self.retries):
            if starved is not skip:
                starved.retry()
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
    """Watches that an owner may narrow while it runs (``rewatch``).

    ``admit`` bounds exact-file descriptors on backends that hold one per file.
    ``exhausted`` opts in to riding out descriptor exhaustion: the hook is told once,
    the watch stays up with what it could register, and the shared ``Changes`` wakes
    retry it. Without the hook, or for any other error, a failure still stops the owner.
    """

    def __init__(self, *paths, changes=None, backend=None, admit=None, exhausted=None):
        self.paths = tuple(normalize(path) for path in paths)
        self.changes = changes or Changes()
        self.backend = backend or native_notify
        self.admit, self.exhausted = admit, exhausted
        self.watcher, self.starved, self.retrying, self.closed = None, False, False, False

    def refresh(self):
        """Register what is wanted and release the rest, even when descriptors run out.

        A registration that fails for want of a descriptor does not end the pass: the walk
        goes on to learn everything that is wanted, the obsolete watches are released (which
        is what makes room, as when a claim narrows the watch), and the pass runs once more.
        """
        for _ in range(2):
            ran_out = self.pass_over()
            if not ran_out:
                return
        raise ran_out[0]

    def pass_over(self):
        ran_out = []

        def add(path):
            if not ran_out:
                try:
                    self.watcher.add(path)
                except OSError as error:
                    if not descriptors_exhausted(error):
                        raise
                    ran_out.append(error)

        self.watcher.retain(plan(self.paths, add, getattr(self.watcher, 'file_vnodes', False),
                                 getattr(self.watcher, 'directory_self_events', True), self.admit))
        return ran_out

    def rewatch(self, *paths, admit=None):
        """Replace what is watched; descriptors for everything else are released now."""
        self.paths, self.admit = tuple(normalize(path) for path in paths), admit
        self.arm()

    def arm(self):
        try:
            if self.watcher is None:
                self.watcher = self.backend(asyncio.get_running_loop(), self.changed, self.failed)
            self.refresh()
        except OSError as error:
            if self.exhausted is None or not descriptors_exhausted(error):
                raise
            if not self.starved:
                self.starved = True
                self.changes.retries.append(self)
                self.exhausted(error)
        else:
            if self.starved:
                self.starved = False
                self.changes.retries.remove(self)

    def retry(self):
        if self.closed or self.retrying:
            return
        self.retrying = True
        try:
            self.arm()
        except Exception as exc:
            self.failed(exc)
        finally:
            self.retrying = False

    def changed(self, paths):
        if self.closed or not (self.starved or any(
                relevant(spec, path) for spec in self.paths for path in paths)):
            return
        try:
            self.arm()
            self.changes.notify(skip=self)
        except Exception as exc:
            self.failed(exc)

    def failed(self, error):
        if not self.closed:
            self.changes.notify(error)

    async def __aenter__(self):
        try:
            self.arm()
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def wait(self, owner=None):
        await self.changes.wait(owner)

    async def __aexit__(self, *args):
        self.closed = True
        if self in self.changes.retries:
            self.changes.retries.remove(self)
        if self.watcher is not None:
            await self.watcher.close()


@asynccontextmanager
async def file_events(*paths):
    async with FileEvents(*paths) as events:
        yield events
