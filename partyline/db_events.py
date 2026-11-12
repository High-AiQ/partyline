"""SQL mutation notifications shared by capability and maintenance subscribers.

SQLite calls the trace synchronously, under Db's transaction lock. Consumers run
on their own loops and take that lock before reading, so they observe completed
transactions. Rollbacks may cause a harmless extra read, never a missed commit.
"""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import re
import threading

from .file_events import Changes

_current = ContextVar('database_event_consumer', default=None)
_MUTATION = re.compile(r'^\s*(?:insert(?:\s+or\s+\w+)?\s+into|replace\s+into|'
                       r'update(?:\s+or\s+\w+)?|delete\s+from)\s+["`\[]?(\w+)', re.I)


class DatabaseEvents:
    def __init__(self, connection):
        self.lock = threading.Lock()
        self.listeners = set()
        self.callbacks = set()
        if wrote := getattr(connection, 'wrote', None):
            self.callbacks.add(wrote)  # the write-ahead log is checkpointed by write volume
        connection.set_trace_callback(self.trace)

    def trace(self, statement):
        match = _MUTATION.match(statement)
        if match is None:
            return
        table = match[1].lower()
        with self.lock:
            listeners, callbacks = list(self.listeners), list(self.callbacks)
        for callback in callbacks:
            callback(statement)
        for listener in listeners:
            if listener is not _current.get() and table in listener.tables:
                try:
                    listener.loop.call_soon_threadsafe(listener.changes.notify)
                except RuntimeError:
                    pass  # subscriber's loop closed during shutdown

    def subscribe(self, *tables):
        return Subscription(self, tables)


class Subscription:
    def __init__(self, source, tables):
        self.source, self.tables = source, set(tables)
        self.loop = asyncio.get_running_loop()
        self.changes = Changes()

    def __enter__(self):
        with self.source.lock:
            self.source.listeners.add(self)
        return self

    def __exit__(self, *args):
        with self.source.lock:
            self.source.listeners.discard(self)

    @contextmanager
    def processing(self):
        token = _current.set(self)
        try:
            yield
        finally:
            _current.reset(token)

    async def wait(self, delay=None):
        if delay is None:
            await self.changes.wait()
        else:
            try:
                await asyncio.wait_for(self.changes.wait(asyncio.current_task()), max(0, delay))
            except TimeoutError:
                pass  # no-poll (b): one deadline computed from persisted state
