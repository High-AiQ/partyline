"""Directory-entry and exact-file vnode events, without timed kqueue waits."""

import os
import select


class KqueueNotify:
    file_vnodes = True  # Directory vnode events alone do not report child-file appends.

    def __init__(self, loop, changed, failed, api=select):
        self.loop, self.changed, self.failed, self.api = loop, changed, failed, api
        self.queue = api.kqueue()
        self.watches = {}
        try:
            loop.add_reader(self.queue.fileno(), self.readable)
        except BaseException:
            self.queue.close()
            raise

    def add(self, path):
        status = path.stat()
        identity = (status.st_dev, status.st_ino)
        if path in self.watches:
            if self.watches[path][1] == identity:
                return
            self.remove(path)
        descriptor = os.open(path, getattr(os, 'O_EVTONLY', os.O_RDONLY) | os.O_CLOEXEC)
        api = self.api
        flags = (api.KQ_NOTE_DELETE | api.KQ_NOTE_WRITE | api.KQ_NOTE_EXTEND |
                 api.KQ_NOTE_ATTRIB | api.KQ_NOTE_RENAME | api.KQ_NOTE_REVOKE)
        try:
            self.queue.control([api.kevent(descriptor, filter=api.KQ_FILTER_VNODE,
                flags=api.KQ_EV_ADD | api.KQ_EV_ENABLE | api.KQ_EV_CLEAR, fflags=flags)], 0)
        except BaseException:
            os.close(descriptor)
            raise
        self.watches[path] = (descriptor, identity)

    def remove(self, path):
        descriptor, _ = self.watches.pop(path)
        os.close(descriptor)  # Closing the fd removes its kevent.

    def retain(self, paths):
        for path in self.watches.keys() - paths:
            self.remove(path)

    def readable(self):
        try:
            incoming = self.queue.control([], max(1, len(self.watches)), 0)
            if any(event.flags & self.api.KQ_EV_ERROR for event in incoming):
                raise OSError('kqueue filesystem registration failed')
            ready = {event.ident for event in incoming}
            self.changed({path for path, (descriptor, _) in self.watches.items() if descriptor in ready})
        except Exception as exc:
            self.failed(exc)

    async def close(self):
        self.loop.remove_reader(self.queue.fileno())
        for path in list(self.watches):
            self.remove(path)
        self.queue.close()
