"""Running out of descriptors is survivable for a watch; no other failure is."""

import asyncio
import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from partyline.adapters.events import AdapterEvents
from partyline.file_events import Changes, FileEvents, descriptors_exhausted


def exhausted():
    return OSError(errno.EMFILE, 'Too many open files')


class Backend:
    """Fails with whatever it is told to, for as many registrations as it is told."""

    def __init__(self, failures=(), creation=()):
        self.failures, self.creation, self.made = list(failures), list(creation), []

    def __call__(self, loop, changed, failed):
        if self.creation:
            raise self.creation.pop(0)
        self.made.append(Watcher(self.failures))
        return self.made[-1]


class Watcher:
    file_vnodes = True

    def __init__(self, failures):
        self.failures, self.watches, self.closed = failures, set(), False

    def add(self, path):
        if self.failures:
            raise self.failures.pop(0)
        self.watches.add(path)

    def retain(self, paths):
        self.watches &= paths

    async def close(self):
        self.closed = True


class Capped(Backend):
    """A host that has room for ``room`` watches at once."""

    def __init__(self, room):
        super().__init__()
        self.room = room

    def __call__(self, loop, changed, failed):
        watcher = super().__call__(loop, changed, failed)
        add = watcher.add

        def limited(path):
            if len(watcher.watches) >= self.room and path not in watcher.watches:
                raise exhausted()
            add(path)

        watcher.add = limited
        return watcher


class ExhaustionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.told = []

    def events(self, backend, hook=True, changes=None):
        return FileEvents(self.root / 'db', backend=backend, changes=changes,
                          exhausted=self.told.append if hook else None)

    def test_only_descriptor_exhaustion_is_classified_as_such(self):
        self.assertTrue(descriptors_exhausted(OSError(errno.ENFILE, 'file table overflow')))
        self.assertTrue(descriptors_exhausted(exhausted()))
        for other in (OSError(errno.EACCES, 'denied'), OSError('plan exceeds 4096 entries'),
                      RuntimeError('boom'), None):
            self.assertFalse(descriptors_exhausted(other))

    async def test_without_the_hook_exhaustion_still_stops_the_owner(self):
        with self.assertRaises(OSError):
            async with self.events(Backend(failures=[exhausted()] * 2), hook=False):
                self.fail('entered')

    async def test_a_registration_that_runs_out_is_told_once_and_retried_on_the_next_wake(self):
        changes, backend = Changes(), Backend(failures=[exhausted()] * 4)  # two passes a wake
        async with self.events(backend, changes=changes) as events:
            self.assertTrue(events.starved)
            self.assertEqual(len(self.told), 1)
            changes.notify()  # still out of descriptors: no second report
            self.assertTrue(events.starved)
            self.assertEqual(len(self.told), 1)
            changes.notify()  # descriptors came back
            self.assertFalse(events.starved)
            self.assertEqual(backend.made[0].watches, {self.root})
            self.assertIsNone(changes.error)
            self.assertEqual(changes.retries, [])

    async def test_a_watch_that_could_not_even_create_its_queue_retries_creation(self):
        changes, backend = Changes(), Backend(creation=[exhausted()])
        async with self.events(backend, changes=changes) as events:
            self.assertIsNone(events.watcher)
            changes.notify()
            self.assertIsNotNone(events.watcher)
            self.assertFalse(events.starved)
        self.assertTrue(backend.made[0].closed)

    async def test_a_native_event_while_starved_retries_whatever_changed(self):
        backend = Backend(failures=[exhausted()] * 2)
        async with self.events(backend) as events:
            events.changed({Path('/elsewhere')})
            self.assertFalse(events.starved)

    async def test_every_other_failure_still_stops_the_owner(self):
        for error in (OSError(errno.EACCES, 'denied'), OSError('plan exceeds 4096 entries'),
                      RuntimeError('boom')):
            with self.subTest(error=error):
                with self.assertRaises(type(error)):
                    async with self.events(Backend(failures=[error])):
                        self.fail('entered')
                changes, backend = Changes(), Backend()
                async with self.events(backend, changes=changes) as events:
                    backend.made[0].failures.append(error)
                    events.changed({self.root / 'db'})
                    with self.assertRaises(type(error)):
                        await changes.wait()

    async def test_a_healthy_peers_event_retries_the_starved_one(self):
        changes = Changes()
        starved = self.events(Backend(creation=[exhausted()]), changes=changes)
        healthy = self.events(Backend(), changes=changes)
        async with starved, healthy:
            self.assertTrue(starved.starved)
            healthy.changed({self.root / 'db'})  # a native event on the healthy watch
            self.assertFalse(starved.starved)
            self.assertIsNotNone(starved.watcher)

    async def test_a_claim_that_cannot_fit_still_releases_what_it_obsoletes(self):
        """Narrowing at capacity: the new file does not fit until the old watches go."""
        for name in ('a', 'b', 'c'):
            (self.root / name).mkdir()
        mine = self.root / 'a' / 'mine.jsonl'
        mine.write_text('{}')
        backend = Capped(4)
        events = FileEvents(self.root / '*' / '*.jsonl', backend=backend,
                            exhausted=self.told.append, admit=lambda path: False)
        async with events:
            self.assertEqual(backend.made[0].watches,
                             {self.root, self.root / 'a', self.root / 'b', self.root / 'c'})
            events.rewatch(mine)
            self.assertFalse(events.starved)
            self.assertEqual(backend.made[0].watches, {self.root / 'a', mine})
        self.assertEqual(self.told, [])

    async def test_a_claim_that_never_fits_keeps_nothing_it_does_not_need(self):
        (self.root / 'a').mkdir()
        mine = self.root / 'a' / 'mine.jsonl'
        mine.write_text('{}')
        backend = Capped(1)
        async with FileEvents(self.root / 'a' / '*.jsonl', backend=backend,
                              exhausted=self.told.append, admit=lambda path: False) as events:
            events.rewatch(mine)
            self.assertTrue(events.starved)
            self.assertEqual(len(self.told), 1)
            self.assertLessEqual(len(backend.made[0].watches), 1)

    async def test_closing_a_starved_watch_forgets_it(self):
        changes = Changes()
        async with self.events(Backend(creation=[exhausted()]), changes=changes):
            self.assertEqual(len(changes.retries), 1)
        self.assertEqual(changes.retries, [])


class Owner(AdapterEvents):
    def __init__(self):
        self.att, self.post = {'name': 'agent'}, AsyncMock()
        self._events_init()


class AdapterReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_line_hears_it_once_however_many_watches_starve(self):
        owner = Owner()
        with tempfile.TemporaryDirectory() as root:
            for _ in range(3):
                backend = Backend(creation=[exhausted()])
                async with owner.file_events(Path(root) / 'db', backend=backend,
                                             changes=owner._changes):
                    pass
        await asyncio.gather(*owner._starved_posts)
        owner.post.assert_awaited_once()
        sender, kind, body = owner.post.await_args.args
        self.assertEqual((sender, kind), ('system', 'system'))
        self.assertIn('file descriptors', body)
        self.assertNotIn('@', body)
