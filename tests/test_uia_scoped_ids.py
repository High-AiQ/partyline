"""A filtered helper read keeps earlier targets, with live stale/consent validation before action."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_action_worker import ActionWorker, run_action
from partyline_helper.uia_query import snapshot as query_snapshot
from partyline_helper.uia_snapshot import snapshot
from tests.test_uia_worker import Provider


class ScopedIDsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = Provider()
        self.provider.nodes[0]['children'].append(2)
        self.provider.nodes[1]['name'] = 'Field A'
        self.provider.nodes.append({'rect': (1, 1, 5, 5), 'name': 'Field B'})
        self.provider.parent = lambda _: 0
        self.session = SimpleNamespace(share=None, accepted=False, window_grant_id='g',
            status=SimpleNamespace(window_title='App', changed=Mock()),
            tools=SimpleNamespace(audit=SimpleNamespace(append=Mock(), ensure_writable=Mock())))
        self.grant = {'hwnd': 1, 'pid': 2, 'title': 'App', 'process': 'app'}
        self.reads = []
        def reader(hwnd, frame=None, state=None, deep=True, **options):
            self.reads.append(options)
            if options.get('query'):
                name = options['query']['query']
                return query_snapshot(self.provider, options['query'],
                    finder=lambda *_: [i for i in (1, 2) if self.provider.nodes[i]['name'] == name])
            return snapshot(self.provider, clock=lambda: 0)
        self.access = WindowAccess(self.session, platform='win32', reader=reader,
                                   list_windows=lambda: [self.grant])
        self.access.grant = self.grant
        self.access.event_status = lambda: {'event_counter': 7}
        self.access.gate.grant()
        self.session.window = self.access
        def runner(*args):
            return run_action(*args, factory=lambda _: self.provider)
        self.worker = ActionWorker(self.session, runner=runner)

    async def act(self, ident):
        return await self.worker.perform({'element_id': ident, 'action': 'set_value', 'value': 'new'})

    async def test_second_field_stays_actionable_and_full_walk_state_survives_query(self):
        full = await self.access.snapshot()
        old_a, old_b = (next(item['id'] for item in full['elements'] if item['name'] == name)
                        for name in ('Field A', 'Field B'))
        path_b = self.access.paths[old_b]
        epoch = self.access.epoch
        self.access.walks['cursor'] = {'stack': []}
        self.assertEqual('completed', (await self.act(old_a))['status'])
        query = await self.access.snapshot({'query_scope': {'query': 'Field A'}})
        self.assertFalse(any(item['name'] == 'Field B' for item in query['elements']))
        self.assertIn(old_b, self.access.elements)
        self.assertEqual(path_b, self.access.paths[old_b])
        self.assertEqual(epoch, self.access.epoch)
        self.assertEqual(7, self.access.event_counter)
        self.assertIn('cursor', self.access.walks)
        self.assertNotEqual(epoch, query['snapshot_id'])
        self.assertEqual('completed', (await self.act(old_b))['status'])
        self.assertEqual([{}, {'query': {'query': 'Field A'}}], self.reads)
        self.assertEqual([(1, 'set_value', 'new'), (2, 'set_value', 'new')], self.provider.calls)

    async def test_retained_target_must_still_pass_live_identity_and_consent_checks(self):
        full = await self.access.snapshot()
        old_b = next(item['id'] for item in full['elements'] if item['name'] == 'Field B')
        await self.access.snapshot({'query_scope': {'query': 'Field A'}})
        self.provider.nodes[2]['same'] = False
        stale = await self.act(old_b)
        self.assertEqual('failed', stale['status'])
        self.assertIn('stale', stale['error'])
        self.assertFalse(self.provider.calls)
        self.provider.nodes[2]['same'] = True
        self.access.gate.invalidate()
        self.assertEqual('revoked', (await self.act(old_b))['error'])
        self.assertFalse(self.provider.calls)

    async def test_full_capture_and_revoke_reset_retained_ids(self):
        full = await self.access.snapshot()
        old_b = next(item['id'] for item in full['elements'] if item['name'] == 'Field B')
        await self.access.snapshot({'query_scope': {'query': 'Field A'}})
        self.provider.nodes[0]['children'] = [1]
        await self.access.snapshot()
        self.assertNotIn(old_b, self.access.elements)
        self.assertNotIn(old_b, self.access.paths)
        self.assertEqual('stale or unknown element', (await self.act(old_b))['error'])
        self.access.revoke()
        self.assertFalse(self.access.elements)
        self.assertFalse(self.access.paths)
        self.assertIsNone(self.access.epoch)

    async def test_failed_query_preserves_earlier_ids_and_the_full_walk(self):
        full = await self.access.snapshot()
        old_b = next(item['id'] for item in full['elements'] if item['name'] == 'Field B')
        epoch = self.access.epoch
        self.access.walks['cursor'] = {'stack': []}
        self.access.reader = lambda *args, **kwargs: {'elements_unavailable': 'query failed'}
        result = await self.access.snapshot({'query_scope': {'query': 'Field A'}})
        self.assertEqual('query failed', result['elements_unavailable'])
        self.assertEqual(epoch, self.access.epoch)
        self.assertIn('cursor', self.access.walks)
        self.assertIn(old_b, self.access.paths)
        self.assertEqual('completed', (await self.act(old_b))['status'])

    async def test_query_events_do_not_rebase_an_earlier_full_walk_counter(self):
        await self.access.snapshot()
        self.access.walks['cursor'] = {'stack': []}
        self.access.event_status = lambda: {'event_counter': 8}
        query = await self.access.snapshot({'query_scope': {'query': 'Field A'}})
        self.assertEqual(8, query['captured_event_counter'])
        self.assertEqual(7, self.access.event_counter)
        result = await self.access.snapshot({'cursor': 'cursor'})
        self.assertIn('inconsistent', result['elements_unavailable'])
        self.assertEqual(2, len(self.reads))

    def test_merged_helper_ids_are_bounded(self):
        result = {'snapshot_id': 'query', 'elements': [{'id': str(i)} for i in range(4)],
                  'paths': {str(i): [i] for i in range(4)}}
        with patch('partyline_helper.uia_access.MAX_RETAINED_IDS', 2):
            self.access.keep(result, None, scoped=True)
        self.assertEqual({'2', '3'}, set(self.access.elements))
        self.assertEqual({'2', '3'}, set(self.access.paths))
