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
            async with self.events(Backend(failures=[exhausted()]), hook=False):
                self.fail('entered')

    async def test_a_registration_that_runs_out_is_told_once_and_retried_on_the_next_wake(self):
        changes, backend = Changes(), Backend(failures=[exhausted(), exhausted()])
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
        backend = Backend(failures=[exhausted()])
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
