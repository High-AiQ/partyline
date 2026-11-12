"""Count the descriptors one Claude adapter holds for file watching, per phase.

The kqueue backend is the real ``KqueueNotify`` with an injected api: its files are
opened for real, only the kernel queue is a stand-in whose events a test delivers.
``held()`` is what the backends say they hold; ``real_fds()`` is the process's own
descriptor table (Linux), which is what keeps ``held()`` honest about leaks.
"""

import asyncio
import json
import os
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.claude.adapter import PartylineAdapter
from partyline.file_events import FileEvents
from partyline.file_notify_kqueue import KqueueNotify
from tests.adapter_event_clock import install as event_clock

_REAL_SLEEP = asyncio.sleep
SPAWNED_AT = 1_000_000.0
LONG_AGO = SPAWNED_AT - 86_400.0


class QuietLoop:
    def __init__(self):
        self.readers = {}

    def add_reader(self, descriptor, callback):
        self.readers[descriptor] = callback

    def remove_reader(self, descriptor):
        del self.readers[descriptor]


class FakeQueue:
    """A kernel queue whose events a test queues by path; closing it is counted."""

    def __init__(self, number):
        self.number, self.events, self.closed = number, [], False

    def fileno(self):
        return 5000 + self.number

    def control(self, changes, count, timeout=None):
        events, self.events = self.events[:count], self.events[count:]
        return events

    def close(self):
        self.closed = True


class Kernel:
    """Every kqueue backend created for one adapter, and what they hold now."""

    def __init__(self):
        self.backends, self.queues = [], []
        self.api = SimpleNamespace(
            kqueue=self.kqueue, kevent=lambda fd, **kw: SimpleNamespace(ident=fd, **kw),
            KQ_NOTE_DELETE=1, KQ_NOTE_WRITE=2, KQ_NOTE_EXTEND=4, KQ_NOTE_ATTRIB=8,
            KQ_NOTE_RENAME=16, KQ_NOTE_REVOKE=32, KQ_FILTER_VNODE=1,
            KQ_EV_ADD=1, KQ_EV_ENABLE=2, KQ_EV_CLEAR=4, KQ_EV_ERROR=8)
        self.loop = QuietLoop()

    def kqueue(self):
        self.queues.append(FakeQueue(len(self.queues)))
        return self.queues[-1]

    def backend(self, loop, changed, failed):
        backend = KqueueNotify(self.loop, changed, failed, self.api)
        self.backends.append(backend)
        return backend

    def live(self):
        return [b for b in self.backends if not b.queue.closed]

    def watched(self):
        return {path for backend in self.live() for path in backend.watches}

    def held(self):
        """Descriptors: one per watched path plus one kernel queue per live backend."""
        return sum(len(b.watches) for b in self.live()) + len(self.live())

    def fire(self, path):
        """Report a vnode event for ``path`` on every backend that watches it."""
        for backend in self.live():
            if Path(path) in backend.watches:
                backend.queue.events.append(
                    SimpleNamespace(ident=backend.watches[Path(path)][0], flags=0))
                backend.readable()


def real_fds():
    try:
        return len(os.listdir('/proc/self/fd'))
    except OSError:  # not Linux: the backends' own account is all there is
        return None


def populate(root, transcripts, directories):
    """``transcripts`` old Claude sessions spread over ``directories`` project dirs."""
    projects = Path(root) / '.claude' / 'projects'
    for number in range(transcripts):
        directory = projects / f'-work-project-{number % directories}'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'old-{number}.jsonl'
        path.write_text(json.dumps({'type': 'mode'}) + '\n', encoding='utf-8')
        os.utime(path, (LONG_AGO, LONG_AGO))
    return projects


def make_adapter(kernel, root, ident='attachment-1', resume=False):
    async def post(*_args):
        return None

    adapter = PartylineAdapter(
        {'command': ['claude'], 'id': ident, 'name': 'claude', 'cwd': '/work',
         'conv_name': 'a line', 'resume': resume,
         'adapter_metadata': {'capabilities': {'transcript': True}}}, post, post)
    event_clock(adapter)
    for name in ('file_events', 'wait_for_change', 'event_time'):
        del adapter.__dict__[name]  # real events: the kernel stand-in delivers them
    adapter.file_events = partial(FileEvents, backend=kernel.backend)
    adapter.spawned_at, adapter.resume = SPAWNED_AT, resume
    adapter._silent_until_wake = False
    adapter.alive = lambda: True
    return adapter


def environment(root):
    return patch.dict(os.environ, {'HOME': str(root), 'USERPROFILE': str(root),
                                   'CLAUDE_CONFIG_DIR': str(Path(root) / '.claude')})


async def settle():
    for _ in range(20):
        await _REAL_SLEEP(0)


class Run:
    """One adapter's ``_run`` driven to a phase, with the CLI's transcript on disk."""

    def __init__(self, kernel, root, **kwargs):
        self.kernel, self.root = kernel, Path(root)
        self.adapter = make_adapter(kernel, root, **kwargs)
        self.posted = []

    async def __aenter__(self):
        self.patches = [
            patch('partyline.adapters.bundled.claude.adapter.asyncio.sleep', AsyncMock()),
            patch.object(self.adapter, 'send_startup_briefing', AsyncMock(return_value=True)),
            patch.object(self.adapter, 'release_startup_delivery', AsyncMock(return_value=True)),
            environment(self.root)]
        for item in self.patches:
            item.start()
        self.task = asyncio.ensure_future(self.adapter._run())
        await settle()
        return self

    def session(self, directory, name, token=True, when=SPAWNED_AT + 5):
        path = self.root / '.claude' / 'projects' / directory / f'{name}.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {'type': 'user', 'cwd': '/work',
                  'message': {'content': self.adapter._claim_token if token else 'chatter'}}
        path.write_text(json.dumps(record) + '\n', encoding='utf-8')
        os.utime(path, (when, when))
        return path

    async def stop(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def __aexit__(self, *args):
        await self.stop()
        for item in reversed(self.patches):
            item.stop()


async def measure(root, transcripts, directories):
    """Descriptors held while searching, while tailing a claimed transcript, after stop."""
    populate(root, transcripts, directories)
    kernel, before = Kernel(), real_fds()
    async with Run(kernel, root) as run:
        searching = kernel.held()
        # The CLI re-execs without the pin and writes a randomly named session.
        mine = run.session('-work-project-0', 'random-name')
        kernel.fire(mine.parent)
        await settle()
        tailing = kernel.held()
        claimed = run.adapter._transcript == str(mine)
        leak = None if before is None else real_fds() - before - sum(
            len(b.watches) for b in kernel.live())
        await run.stop()
    return {'transcripts': transcripts, 'directories': directories, 'searching': searching,
            'tailing': tailing, 'after_stop': kernel.held(), 'claimed': claimed,
            'unaccounted_fds': leak}
