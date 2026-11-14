"""Fake-clock regression coverage for the worker, COM walk, quiet barrier and narrow key path."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline_helper.timing import Timing
from partyline_helper.uia_action_worker import run_action
from partyline_helper.uia_event_state import EventState
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.uia_identity import element_id
from partyline_helper.uia_query import snapshot as query_snapshot, condition, terms
from partyline_helper.uia_snapshot import snapshot
from tests.test_screen_latency import Clock
from tests.test_uia_snapshot import Provider
from tests.test_uia_worker import Provider as ActionProvider
from tests.test_uia_press import PressProvider, Messages
from partyline_helper.uia_press import press


class TimingTests(unittest.TestCase):
    def test_every_phase_accumulates_on_fake_clock_even_on_failure(self):
        clock = Clock()
        timing = Timing(now=clock)
        for name in ('worker_queue_ms', 'initialize_ms', 'target_ms', 'foreground_ms', 'uia_ms',
                     'gate_lock_ms', 'barrier_ms', 'walk_ms', 'reply_ms', 'audit_ms', 'post_read_ms'):
            with timing.phase(name):
                clock.advance(2)
            with self.assertRaises(ValueError), timing.phase(name):
                clock.advance(3)
                raise ValueError
            self.assertEqual(5, timing.values[name])
        self.assertEqual(55, timing.finish({})['timing']['total_ms'])

    def test_action_resolves_once_and_reports_fake_phase_costs(self):
        provider, gate, clock = ActionProvider(), DispatchGate(), Clock()
        generation = gate.grant()
        provider.nodes[1]['patterns'] = ['Invoke']
        grant = {'hwnd': 1, 'pid': 2}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        def now():
            clock.advance(1)
            return clock()
        with patch('partyline_helper.timing.clock', now), \
                patch('partyline_helper.uia_action_worker.prepare', wraps=__import__(
                    'partyline_helper.uia_action', fromlist=['prepare']).prepare) as prepare:
            result = run_action(access, grant, generation,
                {'element_id': element_id(provider, 1, [0]), 'action': 'invoke'}, lambda _: provider)
        prepare.assert_called_once()
        self.assertEqual('completed', result['status'])
        for name in ('initialize_ms', 'target_ms', 'uia_ms', 'gate_lock_ms', 'post_read_ms', 'barrier_ms'):
            self.assertEqual(1, result['timing'][name], name)
        self.assertEqual(2, result['timing']['foreground_ms'])
        self.assertEqual(3, result['timing']['window_check_ms'])
        self.assertEqual('unsupported', result['timing']['barrier_stop'])

    def test_walk_timings_do_not_consume_the_budget_clock(self):
        provider, clock = Provider([{'rect': (0, 0, 1, 1)}]), Clock()
        def now():
            clock.advance(1)
            return clock()
        with patch('partyline_helper.timing.clock', now):
            result = snapshot(provider, clock=lambda: 0)
        self.assertEqual({'walk_ms': 1, 'nodes': 1, 'com_calls': 0, 'total_ms': 2}, result['timing'])


class QueryTests(unittest.TestCase):
    def test_filtered_walk_reads_matches_and_ancestors_only_with_original_path_identity(self):
        provider = Provider([{'rect': (0, 0, 9, 9), 'children': [1, 2]},
                             {'rect': (0, 0, 1, 1), 'children': [3]},
                             {'rect': (0, 0, 1, 1), 'name': 'Save'},
                             {'rect': (0, 0, 1, 1), 'name': 'unrelated'}])
        provider.parent = lambda node: 0
        children = provider.children = Mock(wraps=provider.children)
        result = query_snapshot(provider, {'query': 'Save'}, finder=lambda *_: [2])
        self.assertTrue(result['scoped'])
        self.assertEqual([0, 2], provider.reads)
        children.assert_called_once_with(0)
        self.assertEqual(element_id(provider, 2, [1]), result['elements'][1]['id'])
        self.assertEqual([1], result['paths'][result['elements'][1]['id']])
        self.assertNotIn('unrelated', str(result))

    def test_mid_walk_mutations_skip_the_match_and_mark_the_capture_changed(self):
        for failure in ('removed', 'foreign', 'properties'):
            provider = Provider([{'rect': (0, 0, 9, 9), 'children': [1, 2]},
                                 {'rect': (0, 0, 1, 1), 'name': 'gone'},
                                 {'rect': (0, 0, 1, 1), 'name': 'kept'}])
            provider.parent = lambda _: 0
            if failure == 'removed':
                provider.nodes[0]['children'] = [2]
            elif failure == 'foreign':
                provider.nodes[1]['same'] = False
            else:
                original = provider.properties
                def properties(node, original=original):
                    if node == 1:
                        raise RuntimeError('element no longer available')
                    return original(node)
                provider.properties = properties
            with self.subTest(failure=failure):
                result = query_snapshot(provider, {'query': 'gone|kept'}, finder=lambda *_: [1, 2])
                self.assertTrue(result['changed'])
                self.assertIn('kept', [item['name'] for item in result['elements']])
                self.assertNotIn('gone', [item['name'] for item in result['elements']])

    def test_native_query_compiles_substring_superset_and_type_filter(self):
        automation = Mock()
        provider = SimpleNamespace(automation=automation)
        condition(provider, {'query': '^Save|=OK', 'control_type': 'Button'})
        self.assertEqual([((30005, 'save', 3),), ((30005, 'ok', 1),)],
                         [(call.args,) for call in automation.CreatePropertyConditionEx.call_args_list])
        automation.CreatePropertyCondition.assert_called_once_with(30003, 50000)
        automation.CreateAndCondition.assert_called_once()
        condition(provider, {'control_type': 'unknown'})
        automation.CreateFalseCondition.assert_called_once()
        condition(provider, {'query': '|'})
        automation.CreateTrueCondition.assert_called_once()
        self.assertEqual([('x', True), ('y', False), ('z', True)], terms('^x$|y$|=z'))

    def test_native_search_stays_in_the_control_view_used_by_paths(self):
        from partyline_helper.uia_query import matches
        automation, root = Mock(), Mock()
        root.FindAllBuildCache.return_value = SimpleNamespace(Length=1, GetElement=lambda _: 'match')
        provider = SimpleNamespace(automation=automation, request=Mock(return_value='cache'),
                                   root=lambda: root, popups=lambda: [])
        self.assertEqual(['match'], list(matches(provider, {'query': 'Save'})))
        automation.CreateAndCondition.assert_called_once_with(automation.ControlViewCondition,
                                                             automation.CreatePropertyConditionEx.return_value)
        root.FindAllBuildCache.assert_called_once_with(7, automation.CreateAndCondition.return_value, 'cache')

    def test_press_observation_never_scans_unrelated_children(self):
        provider, messages = PressProvider(), Messages()
        provider.children = Mock(side_effect=AssertionError('unexpected tree walk'))
        # Escape does not need the optional neighbouring submit suggestion.
        result = press(provider, provider.node(1), 'escape', messages)
        self.assertEqual(3, result['posted'])
        provider.children.assert_not_called()
        self.assertEqual(3, len(messages.calls))


class QuietTests(unittest.TestCase):
    def state(self):
        clock = Clock()
        state = EventState(clock=clock, monotonic=clock)
        state.supported, state.subscription = True, SimpleNamespace(live=True)
        return clock, state

    def test_no_event_never_waits_and_unsupported_has_a_reason(self):
        _, state = self.state()
        with patch.object(state.lock, 'wait', side_effect=AssertionError('fixed wait')):
            self.assertEqual('unchanged', state.settle(0))
            state.supported = False
            self.assertEqual('unsupported', state.settle(0))

    def test_real_events_extend_quiet_and_condition_releases_the_lock(self):
        clock, state = self.state()
        state.changed()
        waits = []
        def wait(timeout):
            waits.append(timeout)
            if len(waits) == 1:
                clock.advance(10)
                state.changed()  # notification, not a timer probe, extends quiet
            else:
                clock.advance(21)
        with patch.object(state.lock, 'wait', side_effect=wait):
            self.assertEqual('quiet', state.settle(0))
        self.assertEqual(2, len(waits))
        self.assertAlmostEqual(.02, waits[0])
        self.assertAlmostEqual(.02, waits[1])
        self.assertEqual(2, state.status()['event_counter'])

    def test_event_storm_stops_at_deadline(self):
        clock, state = self.state()
        state.changed()
        def wait(timeout):
            clock.advance(11)
            state.changed()
        with patch.object(state.lock, 'wait', side_effect=wait):
            self.assertEqual('deadline', state.settle(0, budget=.03))


class COMTimingTests(unittest.TestCase):
    def test_interfaces_arguments_accessors_and_failures_are_counted(self):
        from partyline_helper.uia_com_timing import track, unwrap
        class Interface:
            number = 7
            def QueryInterface(self):
                return self
            def child(self, argument, *, other):
                self.args = (argument, other)
                return self
            def fails(self):
                raise ValueError('provider')
        native, counter = Interface(), SimpleNamespace(com_calls=0)
        counted = track(native, counter)
        self.assertTrue(counted)
        self.assertEqual(7, counted.number)
        counted.number = 8
        self.assertIs(native, unwrap(counted.child(counted, other=counted)))
        self.assertEqual((native, native), native.args)
        self.assertEqual(3, counter.com_calls)
        with self.assertRaises(ValueError):
            counted.fails()
        with self.assertRaises(AttributeError):
            _ = counted.missing
        self.assertEqual(5, counter.com_calls)
        self.assertIsNone(track(None, counter))
        self.assertEqual(2, track(2, counter))
