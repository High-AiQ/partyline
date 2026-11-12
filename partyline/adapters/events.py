"""Adapter waits are woken by native file notifications, PTY output, or exit."""

import asyncio
from functools import partial, wraps
import logging

from partyline.file_events import Changes, FileEvents


logger = logging.getLogger(__name__)


class AdapterEvents:
    _watch_events = None

    def narrow_watch(self, *paths):
        """Once a transcript is claimed, watch it (and its directory) instead of the search set."""
        if self._watch_events is not None:
            self._watch_events.rewatch(*paths)

    def file_events(self, *paths, **kwargs):
        """Native watches that ride out running out of descriptors, never any other error."""
        return FileEvents(*paths, exhausted=self._watch_starved, **kwargs)

    def _watch_starved(self, error):
        """Tell the line once; the watch keeps what it has and retries on the next wake."""
        if getattr(self, "_starved_reported", False):
            return
        self._starved_reported = True
        logger.warning("file watches starved of descriptors: %s", error)
        notice = self.post(
            "system", "system",
            f"{self.att.get('name', 'process')}: this host is out of file descriptors, so "
            "some file watches could not be registered. Still attached; the watches are "
            "retried on the next event.")
        task = asyncio.get_running_loop().create_task(notice)
        self.__dict__.setdefault("_starved_posts", set()).add(task)
        task.add_done_callback(self._starved_posts.discard)

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


def watch_files(paths, admit=None):
    """Register before the wrapped scan, and close notifications when it exits.

    ``admit(self, path)`` bounds exact-file descriptors on kqueue hosts; the run may
    ``narrow_watch`` once it knows which file it follows.
    """
    def decorate(run):
        @wraps(run)
        async def wrapped(self, *args, **kwargs):
            roots = paths(self)
            options = {} if admit is None else {"admit": partial(admit, self)}
            async with self.file_events(*roots, changes=self._changes, **options) as events:
                self._watch_events = events
                try:
                    return await run(self, *args, **kwargs)
                finally:
                    self._watch_events = None
        return wrapped
    return decorate
