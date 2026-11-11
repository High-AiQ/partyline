"""Drive memory warnings and browser pushes from native notifications."""

import asyncio
import inspect
import logging
import sys

from .memory_event_policy import MemoryPolicy

logger = logging.getLogger(__name__)


class PendingEvents:
    """Coalesce bursts into one pending set of targets and warning targets."""

    def __init__(self, live_ids=None):
        self.ready = asyncio.Event()
        self.live_ids = live_ids
        self.targets = set()
        self.warning_targets = set()
        self.all_targets = False
        self.all_warnings = False

    def notify(self, ids, warning):
        if self.live_ids is not None:
            live = set(self.live_ids())
            self.targets.intersection_update(live)
            self.warning_targets.intersection_update(live)
            if ids is not None:
                ids = set(ids) & live
                if not ids:
                    return
        if ids is None:
            self.all_targets = True
            self.all_warnings |= warning
        else:
            self.targets.update(ids)
            if warning:
                self.warning_targets.update(ids)
        self.ready.set()

    async def wait(self):
        await self.ready.wait()
        targets = None if self.all_targets else self.targets
        warning = True if self.all_warnings else self.warning_targets
        self.targets, self.warning_targets = set(), set()
        self.all_targets = self.all_warnings = False
        self.ready.clear()
        return targets, warning


def lifecycle_changed(runtime):
    """Re-arm scope watches after a real process has started or resumed."""
    callback = getattr(runtime, "memory_lifecycle_changed", None)
    if callback is not None:
        callback()


def _scope_map(live):
    from .memory_events_linux import scope_path
    result = {}
    for ident, adapter in live.items():
        pid = getattr(getattr(adapter, "proc", None), "pid", None)
        if isinstance(pid, int):
            result[ident] = scope_path(pid)
    return result


def _source(loop, notify):
    if sys.platform.startswith("linux"):
        from .memory_events_linux import LinuxMemoryEvents
        return LinuxMemoryEvents(loop, notify)
    if sys.platform == "win32":
        from .memory_events_windows import WindowsMemoryEvents
        return WindowsMemoryEvents(loop, notify)
    return None


async def run(runtime, *, source_factory=_source, policy=None):
    """Wait on kernel and attachment lifecycle events, without idle reads."""
    pending = PendingEvents(lambda: runtime.live.keys())
    lifecycle = asyncio.Event()
    runtime.memory_lifecycle_changed = lifecycle.set
    source = None
    policy = policy or MemoryPolicy()
    try:
        try:
            source = source_factory(asyncio.get_running_loop(), pending.notify)
        except OSError:
            logger.exception("native memory notification source unavailable")
        # Source callbacks send (attachment ids or None, whether to warn).
        with runtime.db.events.subscribe("attachments") as changes:
            db_wait = asyncio.create_task(changes.wait())
            life_wait = asyncio.create_task(lifecycle.wait())
            event_wait = asyncio.create_task(pending.wait())
            try:
                if source is not None and hasattr(source, "sync"):
                    source.sync(await asyncio.to_thread(_scope_map, dict(runtime.live)))
                while True:
                    done, _ = await asyncio.wait((db_wait, life_wait, event_wait),
                                                 return_when=asyncio.FIRST_COMPLETED)
                    if db_wait in done or life_wait in done:
                        if db_wait in done:
                            db_wait.result()
                            db_wait = asyncio.create_task(changes.wait())
                        if life_wait in done:
                            lifecycle.clear()
                            life_wait = asyncio.create_task(lifecycle.wait())
                        if source is not None and hasattr(source, "sync"):
                            source.sync(await asyncio.to_thread(_scope_map, dict(runtime.live)))
                    if event_wait in done:
                        targets, warning = event_wait.result()
                        try:
                            await policy.handle(runtime, targets, warning)
                        except Exception:
                            logger.exception("memory event processing failed")
                        event_wait = asyncio.create_task(pending.wait())
            finally:
                for task in (db_wait, life_wait, event_wait):
                    task.cancel()
                await asyncio.gather(db_wait, life_wait, event_wait, return_exceptions=True)
    finally:
        runtime.memory_lifecycle_changed = None
        if source is not None:
            closed = source.close()
            if inspect.isawaitable(closed):
                await closed
