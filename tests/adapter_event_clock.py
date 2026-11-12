"""Logical event/deadline driver for transcript fixture state-machine tests.

Existing fixture writers inject their next record through a patched sleeper.
Drive that hook as an event, while advancing an injected clock, without waiting
for native notifications or a real discovery deadline. Event integration tests
exercise the actual Changes/FileEvents path separately.
"""

import asyncio

_REAL_SLEEP = asyncio.sleep


class FixtureFiles:
    def __init__(self, *args, **kwargs):
        pass

    def rewatch(self, *paths, admit=None):
        self.paths = paths

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def install(adapter):
    elapsed = 0.0
    waits = 0

    def clock():
        return elapsed

    async def changed(timeout=None):
        nonlocal elapsed, waits
        waits += 1
        if waits > 1000:
            raise AssertionError('fixture did not stop after 1000 injected events')
        step = min(1.0, timeout) if timeout is not None else 1.0
        elapsed += max(0, step)
        if asyncio.sleep is not _REAL_SLEEP:
            await asyncio.sleep(step)
        await _REAL_SLEEP(0)
        adapter._changes.notify()  # each injected event stands for a file notification
        return max(0, step)

    adapter._events_init()
    adapter.file_events = FixtureFiles
    adapter.event_time = clock
    adapter.wait_for_change = changed
    return adapter
