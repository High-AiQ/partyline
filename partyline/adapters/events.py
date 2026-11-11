"""Adapter waits are woken by native file notifications, PTY output, or exit."""

import asyncio
from functools import wraps

from partyline.file_events import Changes, FileEvents


class AdapterEvents:
    file_events = FileEvents

    def _events_init(self):
        self._changes = Changes()

    async def _tail_jsonl(self, path, handle_line, offset=0):
        from .jsonl_receipts import tail_jsonl
        await tail_jsonl(self, path, handle_line, offset)

    def wake_delivery_waiters(self):
        for name in ('_jsonl_receipt_event', '_confirm_event', '_delivery_confirmed'):
            signal = getattr(self, name, None)
            if signal is not None:
                signal.set()

    def changed(self):
        if not hasattr(self, "_changes"):
            self._events_init()
        self._changes.notify()

    def event_time(self):
        return asyncio.get_running_loop().time()

    async def wait_for_change(self, timeout=None):
        """Wait for a new event, or one explicit deadline (never a periodic tick)."""
        started = asyncio.get_running_loop().time()
        try:
            if timeout is None:
                await self._changes.wait()
            else:
                await asyncio.wait_for(self._changes.wait(asyncio.current_task()), max(0, timeout))
        except TimeoutError:
            pass
        return asyncio.get_running_loop().time() - started


def watch_files(paths):
    """Register before the wrapped scan, and close notifications when it exits."""
    def decorate(run):
        @wraps(run)
        async def wrapped(self, *args, **kwargs):
            roots = paths(self)
            async with self.file_events(*roots, changes=self._changes):
                return await run(self, *args, **kwargs)
        return wrapped
    return decorate
