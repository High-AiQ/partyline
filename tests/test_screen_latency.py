"""Deterministic phase metrics and scoped server reads, including telemetry persistence."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Request

from partyline import screen_timing
from partyline.mcp.telemetry import record
from partyline.screen_element_actions import Then, after
from partyline.screen_timing_contract import extract
from partyline.tool_telemetry_contracts import ToolCall
from tests import test_screen_state_truth as truth

GRANT = truth.GRANT


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def advance(self, milliseconds):
        self.value += milliseconds / 1000


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_nested_phases_and_queue_use_one_fake_clock(self):
        clock = Clock()
        @screen_timing.timed
        async def nested():
            with screen_timing.phase('diff_ms'):
                clock.advance(4)
            screen_timing.helper({'walk_ms': 7, 'nodes': 3, 'barrier_stop': 'quiet'})
            return {}
        @screen_timing.timed
        async def operation(request):
            with screen_timing.phase('window_lock_ms'):
                clock.advance(2)
            return await nested()
        clock.advance(3)
        with patch.object(screen_timing, 'clock', clock):
            result = await operation(Request({'type': 'http', 'screen_received_at': 0.001}))
        self.assertEqual({'request_queue_ms': 2, 'window_lock_ms': 2, 'diff_ms': 4,
                          'helper_walk_ms': 7, 'helper_nodes': 3, 'helper_barrier_stop': 'quiet',
                          'server_total_ms': 6}, result['timing'])
        self.assertIsNone(screen_timing.current.get())

    async def test_context_cleans_up_after_exception(self):
        @screen_timing.timed
        async def operation():
            raise ValueError('failure')
        with self.assertRaises(ValueError):
            await operation()
        self.assertIsNone(screen_timing.current.get())
        with screen_timing.phase('ignored'):
            screen_timing.helper({'uia_ms': 1})

    def test_telemetry_keeps_only_fixed_numeric_phases_and_stop_reasons(self):
        value = {'timing': {'target_ms': 2, 'helper_uia_ms': 3, 'helper_barrier_stop': 'quiet',
                            'helper_ax_tree_ms': 4, 'helper_dispatch_proof_ms': 5,
                            'secret': 'page contents', 'diff_ms': float('nan'), 'send_ms': -1,
                            'answer_ms': True}}
        item = record('screen_element_action', {'action': 'invoke'}, '{}', value, False, 0)
        self.assertEqual({'target_ms': 2, 'helper_uia_ms': 3, 'helper_barrier_stop': 'quiet',
                          'helper_ax_tree_ms': 4, 'helper_dispatch_proof_ms': 5}, item['timing'])
        # Real records use a bounded elapsed clock, not the artificial started=0 above.
        item['latency_ms'] = 1
        metrics = {key: value for key, value in item.items() if key != "_transcript"}
        self.assertEqual(item['timing'], ToolCall.model_validate(metrics).model_dump()['timing'])
        for value in (None, [], {}, {'timing': []}):
            self.assertEqual({}, extract(value))


class ScopedReadTests(unittest.IsolatedAsyncioTestCase):
    status = truth.StateTests.status
    async def exchange(self, principal, grant, device, kind, **fields):
        if fields.get('event_status'):
            return await truth.StateTests.exchange(self, principal, grant, device, kind, **fields)
        self.scopes.append(fields.get('query_scope'))
        if fields.get('query_scope'):
            self.captures += 1
            name = 'Other' if fields['query_scope'].get('query') == 'Other' else 'Save'
            ident = 'fedcba9876543210' if name == 'Other' else '0123456789abcdef'
            return {'scoped': True, 'elements': [{'id': ident, 'name': name,
                    'control_type': 'Button', 'enabled': True}], 'snapshot_id': 'query',
                    'captured_event_counter': self.counter, **self.status()}
        return await truth.StateTests.exchange(self, principal, grant, device, kind, **fields)

    async def asyncSetUp(self):
        self.scopes = []
        await truth.StateTests.asyncSetUp(self)

    async def test_then_query_uses_filtered_capture_and_cannot_supply_a_summary(self):
        hub = SimpleNamespace(elements=self.hub)
        result = await after(hub, self.principal, GRANT, Then(query='Save'), {'status': 'completed'})
        self.assertEqual([{'query': 'Save'}], self.scopes)
        self.assertIn('0123456789abcdef', result['lines'])
        self.assertEqual(('0123456789abcdef', True), self.hub.locked_target('g', '0123456789abcdef'))
        await self.hub.read(self.principal, window='g')
        self.assertIsNone(self.scopes[-1])

    async def test_complete_cached_tree_answers_queries_without_recapturing(self):
        await self.hub.read(self.principal, window='g')
        captures = self.captures
        await self.hub.read(self.principal, window='g', options={'query': 'Save'})
        self.assertEqual(captures, self.captures)

    async def test_query_scope_survives_capture_race(self):
        exchange = self.hub.exchange
        calls = []
        async def racing(*args, **fields):
            result = await exchange(*args, **fields)
            if fields.get('query_scope'):
                calls.append(fields['query_scope'])
                if len(calls) == 1:
                    self.counter += 1
                    result['event_counter'] = self.counter
            return result
        self.hub.exchange = racing
        await self.hub.read(self.principal, window='g', options={'query': 'Save'})
        self.assertEqual([{'query': 'Save'}, {'query': 'Save'}], calls)

    async def test_expired_action_mapping_uses_live_barrier_without_a_capture(self):
        await self.hub.read(self.principal, window='g')
        tree = self.hub.snapshots['g']
        ident = tree.order[0]
        captures = self.captures
        self.hub.clock = lambda: 4
        self.assertIsNone(self.hub.fresh('g'))
        result = await self.hub.action_target(self.principal, GRANT, ident)
        self.assertEqual((tree.nodes[ident].helper, True), result)
        self.assertEqual(captures, self.captures)
        self.assertEqual(0, tree.created)  # no fabricated capture timestamp

    def test_filtered_capture_preserves_known_stable_ids_without_claiming_new_identities(self):
        from partyline.screen_tree import Snapshot
        complete = Snapshot('full', 0)
        items = [{'id': 'window', 'control_type': 'Window', 'name': 'App'},
                 {'id': '0123456789abcdef', 'parent': 'window', 'control_type': 'Button', 'name': 'Save'}]
        complete.add(items)
        scoped = Snapshot('query', 0, complete.space)
        scoped.scoped = True
        scoped.prior_helpers = dict(complete.by_helper)
        scoped.add(items)
        self.assertEqual(complete.by_helper, scoped.by_helper)

    async def test_action_on_second_field_after_then_query_needs_no_full_reread(self):
        from unittest.mock import Mock
        from partyline.screen_element_actions import ElementAction, element_action
        exchange = self.hub.exchange
        sent = []
        async def fields(principal, grant, device, kind, **options):
            if kind == 'window_element_action':
                sent.append(options['element_id'])
                return {'status': 'completed'}
            result = await exchange(principal, grant, device, kind, **options)
            if not options.get('event_status') and not options.get('query_scope'):
                result['elements'] += [
                    {'id': 'field-a', 'parent': 'w', 'control_type': 'Edit', 'name': 'Field A'},
                    {'id': 'field-b', 'parent': 'w', 'control_type': 'Edit', 'name': 'Field B'}]
            return result
        self.hub.exchange = fields
        self.principal.name = 'agent'
        await self.hub.read(self.principal, window='g')
        complete = self.hub.snapshots['g']
        old_a, old_b = (complete.by_helper[ident] for ident in ('field-a', 'field-b'))
        outer = SimpleNamespace(elements=self.hub, window_grants=SimpleNamespace(spend=Mock()))
        with patch('partyline.screen_element_actions.resolve_window', return_value=(GRANT, self.device)), \
                patch('partyline.screen_element_actions.request_principal', return_value=self.principal), \
                patch('partyline.screen_element_actions.deny_unless'):
            result = await element_action(SimpleNamespace(db=None), outer, 'line', ElementAction(
                element_id=old_a, action='set_value', value='A', then=Then(query='Save')), None)
            self.assertIn('Save', result['after']['lines'])
            self.assertEqual(('field-a', True), self.hub.locked_target('g', old_a))
            self.assertEqual(('field-b', True), self.hub.locked_target('g', old_b))
            self.assertEqual(('field-b', True), self.hub.helper_id('g', old_b))
            result = await element_action(SimpleNamespace(db=None), outer, 'line', ElementAction(
                element_id=old_b, action='set_value', value='B'), None)
        self.assertEqual('completed', result['status'])
        self.assertEqual(['field-a', 'field-b'], sent)
        self.assertEqual([None, {'query': 'Save'}], self.scopes)
        self.assertEqual(2, self.captures)

    async def test_different_queries_retain_earlier_query_ids_until_a_full_refresh(self):
        await self.hub.read(self.principal, window='g')
        complete = self.hub.snapshots['g']
        old_id = complete.order[-1]
        await self.hub.read(self.principal, window='g', options={'query': 'Save', 'refresh': True})
        query_id = self.hub.snapshots['g'].by_helper['0123456789abcdef']
        await self.hub.read(self.principal, window='g', options={'query': 'Other', 'refresh': True})
        self.assertNotIn(query_id, self.hub.snapshots['g'].nodes)
        self.assertEqual(('link', True), await self.hub.action_target(self.principal, GRANT, old_id))
        self.assertEqual(('0123456789abcdef', True), self.hub.locked_target('g', query_id))
        self.assertGreater(self.hub.stored(), len(self.hub.snapshots['g'].order))
        await self.hub.read(self.principal, window='g', options={'refresh': True})
        self.assertEqual((query_id, False), self.hub.locked_target('g', query_id))
        self.assertFalse(self.hub.snapshots['g'].action_ids)

    async def test_query_capture_race_keeps_action_fallback_and_failed_query_keeps_previous(self):
        await self.hub.read(self.principal, window='g')
        original = self.hub.snapshots['g']
        old_id = original.order[-1]
        exchange = self.hub.exchange
        queries = []
        async def race(*args, **options):
            result = await exchange(*args, **options)
            if options.get('query_scope'):
                queries.append(True)
                if len(queries) == 1:
                    self.counter += 1
                    result['event_counter'] = self.counter
            return result
        self.hub.exchange = race
        await self.hub.read(self.principal, window='g', options={'query': 'Save', 'refresh': True})
        self.assertEqual(2, len(queries))
        self.assertEqual(('link', True), self.hub.locked_target('g', old_id))
        before_failure = self.hub.snapshots['g']
        async def unavailable(*args, **options):
            return {'elements_unavailable': 'query failed'}
        self.hub.exchange = unavailable
        result = await self.hub.read(self.principal, window='g', options={'query': 'New', 'refresh': True})
        self.assertEqual('query failed', result['elements_unavailable'])
        self.assertIs(before_failure, self.hub.snapshots['g'])
        self.assertEqual(('link', True), self.hub.locked_target('g', old_id))

    def test_retained_action_map_is_bounded(self):
        from partyline.screen_tree import Snapshot
        previous = Snapshot('full', 0)
        previous.add([{'id': str(i), 'name': str(i)} for i in range(4)])
        scoped = Snapshot('query', 0)
        with patch('partyline.screen_tree.MAX_TREE', 2):
            scoped.retain_actions(previous)
        self.assertEqual(2, len(scoped.action_ids))
        self.assertEqual(2, len(scoped.prior_helpers))
