"""A Claude adapter holds descriptors for what can still matter, not for the machine's history.

The invariant these tests state: every transcript the search would read
(``_may_hold_our_token``) is either held by the watch or reported by its directory when
it appears, so a session this activation owns is never missed. Once one is claimed the
adapter watches that file and its directory only.
"""

import json
import os
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path

from partyline.adapters.bundled.claude.adapter import LATER_LOOK_SECONDS, PartylineAdapter
from partyline.adapters.bundled.claude.watch import OLD_SESSIONS_HELD
from partyline.file_events import FileEvents
from partyline.file_notify_linux import LinuxNotify
from tests import watch_descriptors as w


def assistant(text):
    return {'type': 'assistant', 'uuid': text, 'timestamp': 't',
            'message': {'content': [{'type': 'text', 'text': text}]}}


async def until(condition):
    for _ in range(5000):
        if condition():
            return
        await w._REAL_SLEEP(0)
    raise AssertionError('the expected event never arrived')


class DescriptorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        PartylineAdapter._CLAIMED.clear()
        self.addCleanup(PartylineAdapter._CLAIMED.clear)

    async def test_counts_stay_small_however_long_the_history_is(self):
        for transcripts, directories in ((60, 6), (240, 24)):
            with self.subTest(transcripts=transcripts), tempfile.TemporaryDirectory() as root:
                counts = await w.measure(root, transcripts, directories)
                self.assertTrue(counts['claimed'])
                # projects/ and each project directory, plus the one kernel queue.
                self.assertEqual(counts['searching'], directories + 2)
                # The claimed file and its directory, in the run-wide watch and the tail's own.
                self.assertEqual(counts['tailing'], 6)
                self.assertEqual(counts['after_stop'], 0)

    async def test_the_old_watch_cost_one_descriptor_per_transcript(self):
        """The measurement the change started from, kept so the contrast is reproducible."""
        kernel = w.Kernel()
        projects = w.populate(self.root, 60, 6)
        with w.environment(self.root):
            async with FileEvents(str(projects / '*' / '*.jsonl'), backend=kernel.backend):
                self.assertEqual(kernel.held(), 60 + 6 + 1 + 1)

    async def test_no_descriptor_leaks_through_a_whole_run(self):
        w.populate(self.root, 30, 3)
        before = w.real_fds()
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            run.session('-work-project-1', 'random-name')
            await w.settle()
        if before is not None:
            self.assertEqual(w.real_fds(), before)
        self.assertEqual(kernel.held(), 0)

    async def test_old_unrelated_sessions_hold_nothing_and_recent_ones_are_released_at_claim(self):
        w.populate(self.root, 20, 4)
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            self.assertFalse([p for p in kernel.watched() if p.name.startswith('old-')])
            stranger = run.session('-work-project-2', 'stranger', token=False)
            kernel.fire(stranger.parent)
            await w.settle()
            self.assertIn(stranger, kernel.watched())  # written since spawn: it can still matter
            mine = run.session('-work-project-3', 'random-name')
            kernel.fire(mine.parent)
            await w.settle()
            self.assertEqual(run.adapter._transcript, str(mine))
            self.assertEqual(kernel.watched(), {mine, mine.parent})

    async def test_a_pinned_session_created_after_start_is_found_by_its_directory(self):
        w.populate(self.root, 10, 2)
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            mine = run.session('-work-project-0', 'attachment-1')
            kernel.fire(mine.parent)
            await w.settle()
            self.assertEqual(run.adapter._transcript, str(mine))

    async def test_a_reexec_into_a_new_project_directory_is_found(self):
        w.populate(self.root, 10, 2)
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            projects = self.root / '.claude' / 'projects'
            mine = run.session('-work-brand-new', 'random-name')
            kernel.fire(projects)  # the new directory is announced by its parent
            await w.settle()
            self.assertEqual(run.adapter._transcript, str(mine))

    async def test_a_resumed_session_appended_to_wakes_the_search(self):
        """The pinned file is old, so it is held by name, not because it is recent."""
        w.populate(self.root, 10, 2)
        pinned = self.root / '.claude' / 'projects' / '-work-project-1' / 'attachment-1.jsonl'
        pinned.write_text(json.dumps({'type': 'mode'}) + '\n', encoding='utf-8')
        os.utime(pinned, (w.LONG_AGO, w.LONG_AGO))
        kernel = w.Kernel()
        async with w.Run(kernel, self.root, resume=True) as run:
            self.assertIn(pinned, kernel.watched())
            self.assertEqual({p.name for p in kernel.watched() if p.suffix == '.jsonl'},
                             {'attachment-1.jsonl'})
            record = {'type': 'user', 'cwd': '/work',
                      'message': {'content': run.adapter._claim_token}}
            with pinned.open('a', encoding='utf-8') as file:
                file.write(json.dumps(record) + '\n')
            os.utime(pinned, (w.SPAWNED_AT + 5, w.SPAWNED_AT + 5))
            kernel.fire(pinned)
            await w.settle()
            self.assertEqual(run.adapter._transcript, str(pinned))
            self.assertEqual(kernel.watched(), {pinned, pinned.parent})

    async def test_the_claimed_tail_follows_appends_rotation_and_recreation(self):
        w.populate(self.root, 10, 2)
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            run.adapter._fresh = lambda _stamp: True
            posted = []

            async def post(sender, kind, body):
                posted.append(body)

            run.adapter.post = post
            mine = run.session('-work-project-1', 'random-name')
            kernel.fire(mine.parent)
            await until(lambda: getattr(run.adapter, '_jsonl_tail_path', None) == str(mine))
            self.assertEqual(kernel.watched(), {mine, mine.parent})

            async def write(text, mode='a'):
                with mine.open(mode, encoding='utf-8') as file:
                    file.write(json.dumps(assistant(text)) + '\n')

            await write('appended')
            kernel.fire(mine)
            await until(lambda: posted == ['appended'])

            replacement = mine.with_name('swap')  # rotation: a new file takes the name
            replacement.write_text(json.dumps(assistant('rotated')) + '\n', encoding='utf-8')
            os.replace(replacement, mine)
            kernel.fire(mine.parent)
            await until(lambda: 'rotated' in posted)

            mine.unlink()  # unlink, then recreate
            kernel.fire(mine)
            await w.settle()
            await write('recreated', 'w')
            kernel.fire(mine.parent)
            await until(lambda: 'recreated' in posted)
            self.assertEqual(kernel.watched(), {mine, mine.parent})
            self.assertEqual(posted, ['appended', 'rotated', 'recreated'])

    async def test_an_old_unpinned_session_that_takes_our_token_after_the_last_wake_is_found(self):
        """No descriptor is held for it, and the CLI's last pty output may precede its flush."""
        w.populate(self.root, 10, 2)
        old = self.root / '.claude' / 'projects' / '-work-project-0' / 'old-0.jsonl'
        adapter = w.make_adapter(w.Kernel(), self.root)
        waits, now = [], 0.0
        record = {'type': 'user', 'cwd': '/work', 'message': {'content': adapter._claim_token}}

        async def wait(timeout=None):
            nonlocal now
            waits.append(timeout)
            if len(waits) == 2:  # the later look: the flush landed while nothing was running
                with old.open('a', encoding='utf-8') as file:
                    file.write(json.dumps(record) + '\n')
                os.utime(old, (w.SPAWNED_AT + 5, w.SPAWNED_AT + 5))
            now += 0.1 if len(waits) == 1 else timeout
            return 0.1 if len(waits) == 1 else timeout

        adapter.wait_for_change, adapter.event_time = wait, lambda: now
        with w.environment(self.root):
            self.assertEqual(await adapter._await_transcript(), str(old))
        self.assertEqual(waits[1], LATER_LOOK_SECONDS)  # one look, right after the wake

    async def test_an_existing_session_of_this_directory_is_held_so_a_late_token_is_seen(self):
        """No timing assumption: a descriptor reports the append whenever it happens."""
        w.populate(self.root, 10, 2)
        own = self.root / '.claude' / 'projects' / '-work'  # where Claude files /work's sessions
        own.mkdir(parents=True)
        names = [f'existing-{n}.jsonl' for n in range(OLD_SESSIONS_HELD + 5)]
        for number, name in enumerate(names):
            (own / name).write_text(json.dumps({'type': 'mode'}) + '\n', encoding='utf-8')
            os.utime(own / name, (w.LONG_AGO + number, w.LONG_AGO + number))
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            held = {p.name for p in kernel.watched() if p.parent == own}
            self.assertEqual(held, set(names[-OLD_SESSIONS_HELD:]))  # the newest, not all
            self.assertFalse([p for p in kernel.watched() if p.name.startswith('old-')])
            adapter = run.adapter
            quiet = own / names[-1]  # the CLI continues an old, unpinned session
            record = {'type': 'user', 'cwd': '/work', 'message': {'content': adapter._claim_token}}
            with quiet.open('a', encoding='utf-8') as file:
                file.write(json.dumps(record) + '\n')
            os.utime(quiet, (w.SPAWNED_AT + 90, w.SPAWNED_AT + 90))
            kernel.fire(quiet)  # the only event there will ever be
            await w.settle()
            self.assertEqual(adapter._transcript, str(quiet))
            self.assertEqual(kernel.watched(), {quiet, own})

    async def test_the_65th_session_is_claimed_on_a_terminal_output_wake_alone(self):
        """Past the held set no descriptor reports the append; the next pty chunk does.

        Pasting a wake into the CLI always produces terminal output, ``Adapter.changed()``
        runs for every chunk, and each wake rescans by mtime and size.
        """
        own = self.root / '.claude' / 'projects' / '-work'
        own.mkdir(parents=True)
        for number in range(OLD_SESSIONS_HELD + 1):
            path = own / f'existing-{number}.jsonl'
            path.write_text(json.dumps({'type': 'mode'}) + '\n', encoding='utf-8')
            os.utime(path, (w.LONG_AGO + number, w.LONG_AGO + number))
        oldest = own / 'existing-0.jsonl'
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            self.assertEqual(len([p for p in kernel.watched() if p.parent == own]),
                             OLD_SESSIONS_HELD)
            self.assertNotIn(oldest, kernel.watched())
            record = {'type': 'user', 'cwd': '/work',
                      'message': {'content': run.adapter._claim_token}}
            with oldest.open('a', encoding='utf-8') as file:
                file.write(json.dumps(record) + '\n')
            os.utime(oldest, (w.SPAWNED_AT + 90, w.SPAWNED_AT + 90))
            await w.settle()
            self.assertIsNone(run.adapter._transcript or None)  # no file event: still searching
            run.adapter.changed()  # the CLI's next chunk of terminal output; nothing else
            await w.settle()
            self.assertEqual(run.adapter._transcript, str(oldest))

    async def test_a_file_that_became_recent_without_our_token_is_held_for_its_next_append(self):
        w.populate(self.root, 6, 2)
        old = self.root / '.claude' / 'projects' / '-work-project-1' / 'old-1.jsonl'
        kernel = w.Kernel()
        async with w.Run(kernel, self.root) as run:
            self.assertNotIn(old, kernel.watched())
            os.utime(old, (w.SPAWNED_AT + 5, w.SPAWNED_AT + 5))  # someone wrote it; no wake
            run.adapter.changed()  # a later wake finds no token, and re-plans
            await w.settle()
            self.assertIn(old, kernel.watched())
            record = {'type': 'user', 'cwd': '/work',
                      'message': {'content': run.adapter._claim_token}}
            with old.open('a', encoding='utf-8') as file:
                file.write(json.dumps(record) + '\n')
            kernel.fire(old)
            await w.settle()
            self.assertEqual(run.adapter._transcript, str(old))

    async def test_a_look_that_finds_nothing_arms_nothing_more(self):
        w.populate(self.root, 3, 1)
        adapter = w.make_adapter(w.Kernel(), self.root)
        waits, now = [], 0.0
        alive = iter(range(4))
        adapter.alive = lambda: next(alive, None) is not None

        async def wait(timeout=None):
            nonlocal now
            waits.append(timeout)
            now += 0.1 if len(waits) == 1 else LATER_LOOK_SECONDS
            return 0.1 if len(waits) == 1 else LATER_LOOK_SECONDS

        adapter.wait_for_change, adapter.event_time = wait, lambda: now
        with w.environment(self.root):
            self.assertIsNone(await adapter._await_transcript())
        self.assertEqual(waits[:3], [45.0, LATER_LOOK_SECONDS, waits[2]])
        self.assertGreater(waits[2], LATER_LOOK_SECONDS)  # back to the long deadline

    @unittest.skipUnless(sys.platform == 'linux', 'native inotify')
    async def test_inotify_watches_narrow_too_and_unrelated_writes_stop_waking(self):
        w.populate(self.root, 12, 3)
        loop = w.QuietLoop()
        backends = []

        def backend(_, changed, failed):
            backends.append(LinuxNotify(loop, changed, failed))
            return backends[-1]

        run = w.Run(w.Kernel(), self.root)
        run.adapter.file_events = partial(FileEvents, backend=backend)
        async with run:
            outer = backends[0]
            self.assertEqual(len(outer.watches), 3 + 1)  # each project directory and projects/
            stranger = run.session('-work-project-0', 'stranger', token=False)
            mine = run.session('-work-project-2', 'random-name')
            outer.readable()
            await w.settle()
            self.assertEqual(run.adapter._transcript, str(mine))
            self.assertEqual(set(outer.watches), {mine.parent})
            before = run.adapter._changes.version
            stranger.write_text('{}\n')
            outer.readable()
            await w.settle()
            self.assertEqual(run.adapter._changes.version, before)  # a stranger no longer wakes it
