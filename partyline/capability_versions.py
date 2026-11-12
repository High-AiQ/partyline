"""Event-driven capability revisions for MCP tool-list refresh."""

import asyncio
import re
import secrets
import threading


def bump_runtime(runtime):
    if versions := getattr(runtime, "capability_versions", None):
        versions.bump_all()


class CapabilityVersions:
    def __init__(self, db=None):
        self.epoch = secrets.token_hex(8)
        self._lock = threading.Lock()
        self._versions = {}
        self._waiters = {}
        self._closed = False
        self._tables = {"attachments", "conversations", "conversation_write_grants",
                        "task_reviews", "screen_window_grants"}
        if db is not None:
            db.events.callbacks.add(self.changed_by_sql)

    def current(self, attachment_id):
        with self._lock:
            value = self._versions.setdefault(attachment_id, 0)
            return f"{self.epoch}:{value}"

    def changed_by_sql(self, statement):
        words = statement.strip().lower().split()
        if len(words) < 3:
            return
        operation = words[0]
        if operation == "insert" and "into" in words:
            table = words[words.index("into") + 1]
        elif operation == "update":
            table = words[1]
        elif operation == "delete" and len(words) > 2 and words[1] == "from":
            table = words[2]
        else:
            return
        table = table.strip('"`[]').split(".")[-1]
        if table not in self._tables:
            return
        if operation == "update":
            assignments = statement.lower().split(" set ", 1)
            if len(assignments) != 2:
                return
            columns = {"attachments": ("is_lead", "is_successor", "status", "conv_id", "adapter"),
                       "conversation_write_grants": ("path",),
                       "conversations": ("parent_id", "archived_at")}.get(table, ())
            clause = assignments[1].split(" where ", 1)[0]
            if not any(re.search(rf"\b{column}\s*=", clause) for column in columns):
                return
        self.bump_all()

    def bump_all(self):
        with self._lock:
            for attachment_id in self._versions:
                self._versions[attachment_id] += 1
            waiters = [waiter for entries in self._waiters.values() for waiter in entries]
        self._wake(waiters)

    @staticmethod
    def _wake(waiters):
        for loop, event in waiters:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass  # The request's event loop has already closed.

    def close(self):
        """Shutdown: end every open stream, so no request outlives the listener."""
        with self._lock:
            self._closed = True
            waiters = [waiter for entries in self._waiters.values() for waiter in entries]
        self._wake(waiters)

    async def wait_for_change(self, attachment_id, since):
        """The revision once it differs from ``since``; None once the server is stopping.

        Nothing bounds the wait: a change or shutdown is the only thing that ends it.
        """
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        waiter = (loop, event)
        with self._lock:
            if self._closed:
                return None
            current = f"{self.epoch}:{self._versions.setdefault(attachment_id, 0)}"
            if since != current:
                return current
            self._waiters.setdefault(attachment_id, set()).add(waiter)
        try:
            await event.wait()
        finally:
            with self._lock:
                entries = self._waiters.get(attachment_id)
                if entries:
                    entries.discard(waiter)
                    if not entries:
                        self._waiters.pop(attachment_id, None)
        return None if self._closed else self.current(attachment_id)

    async def changes(self, attachment_id):
        """The current revision at once, then each later one, until shutdown."""
        since = None
        while (since := await self.wait_for_change(attachment_id, since)) is not None:
            yield since
