"""Delay is measured on real operations with a fake clock; nothing waits or polls."""

import asyncio
import importlib.util
import logging
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI

from partyline import op_timing
from partyline.adapters.loader import BUNDLED_ROOT, load_bundled_adapters
from partyline.adapters.registry import ADAPTERS, make_adapter
from partyline.screen_hub import ScreenHub
from partyline.terminal_stream import _send_terminal
from partyline.terminal_viewers import TerminalViewerRegistry
from partyline.ws_push import push_event
from tests import test_opencode_v2_adapter as v2_tests

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'tok-SECRET-capability'


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TimingCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        for target, value in (('clock', self.clock), ('THRESHOLD', 0.25), ('COOLDOWN', 10.0)):
            patcher = patch.object(op_timing, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        op_timing.reset()
        self.addCleanup(op_timing.reset)

    def app(self):
        app = FastAPI()

        @app.get('/items/{item_id}')
        async def item(item_id: str, seconds: float = 0.0):
            self.clock.advance(seconds)
            return {'ok': True}

        op_timing.install(app)
        return app

    async def get(self, app, url):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            return await client.get(url)

    def logged(self):
        return self.assertLogs('partyline.op_timing', level=logging.WARNING)


class HttpTest(TimingCase):
    async def test_slow_handler_is_recorded_flagged_and_names_the_route_template(self):
        app = self.app()
        with self.logged() as logs:
            await self.get(app, f'/items/{SECRET}?seconds=0.3&token={SECRET}')
        self.assertEqual(len(logs.output), 1)
        self.assertIn('GET /items/{item_id}', logs.output[0])
        self.assertIn('300 ms', logs.output[0])
        self.assertNotIn(SECRET, logs.output[0])
        stat = op_timing.stats()['GET /items/{item_id}']
        self.assertEqual((stat['count'], stat['slow']), (1, 1))
        self.assertAlmostEqual(stat['max'], 0.3)
        self.assertEqual(op_timing.recent_slow()[0][0], 'GET /items/{item_id}')

    async def test_fast_request_is_counted_but_not_flagged(self):
        app = self.app()
        with self.assertNoLogs('partyline.op_timing', level=logging.WARNING):
            await self.get(app, '/items/a?seconds=0.25')
        stat = op_timing.stats()['GET /items/{item_id}']
        self.assertEqual((stat['count'], stat['slow']), (1, 0))

    async def test_warning_is_rate_limited_per_name_without_a_timer(self):
        app = self.app()
        with self.logged() as logs:
            await self.get(app, '/items/a?seconds=0.3')
            self.clock.advance(5)
            await self.get(app, '/items/b?seconds=0.3')
            self.clock.advance(5)
            await self.get(app, '/items/c?seconds=0.3')
        self.assertEqual(len(logs.output), 2)
        self.assertEqual(op_timing.stats()['GET /items/{item_id}']['slow'], 3)

    async def test_unmatched_path_is_named_without_the_path(self):
        app = self.app()
        await self.get(app, f'/nope/{SECRET}')
        self.assertEqual(list(op_timing.stats()), ['GET unrouted'])

    async def test_websocket_scopes_pass_through_untimed(self):
        inner = AsyncMock()
        await op_timing.OpTimingMiddleware(inner)({'type': 'websocket'}, None, None)
        inner.assert_awaited_once()
        self.assertEqual(op_timing.stats(), {})

    async def test_failing_handler_is_still_timed(self):
        async def broken(scope, receive, send):
            self.clock.advance(0.4)
            raise RuntimeError('boom')

        scope = {'type': 'http', 'method': 'POST'}
        with self.logged(), self.assertRaises(RuntimeError):
            await op_timing.OpTimingMiddleware(broken)(scope, None, None)
        self.assertEqual(op_timing.stats()['POST unrouted']['slow'], 1)

    async def test_names_are_bounded(self):
        for number in range(op_timing.MAX_NAMES + 20):
            op_timing.record(f'name {number}', 0.0)
        self.assertLessEqual(len(op_timing.stats()), op_timing.MAX_NAMES + 1)
        self.assertIn('other', op_timing.stats())


class PushTest(TimingCase):
    def runtime(self, *sockets):
        return MagicMock(sockets={'line': set(sockets)}, human_handles={})

    def socket(self, delay=0.0, fail=False):
        async def send(payload):
            self.clock.advance(delay)
            if fail:
                raise ConnectionError
        return MagicMock(send_json=send)

    async def test_slow_socket_delays_later_pushes_and_is_flagged(self):
        slow, behind = self.socket(0.3), self.socket(0.0)
        runtime = self.runtime(slow)
        with self.logged() as logs:
            await push_event(runtime, 'line', {'type': 'message', 'message': {'body': SECRET}})
        self.assertIn('push message', logs.output[0])
        self.assertNotIn(SECRET, logs.output[0])
        runtime.sockets['line'].add(behind)
        op_timing.reset()
        with self.logged():
            await push_event(self.runtime(slow, behind), 'line', {'type': 'message'})
        self.assertEqual(op_timing.stats()['push message']['count'], 2)

    async def test_failed_socket_is_dropped_and_still_counted(self):
        bad = self.socket(fail=True)
        runtime = self.runtime(bad)
        await push_event(runtime, 'line', {'type': 'attachment'})
        self.assertEqual(runtime.sockets['line'], set())
        self.assertEqual(op_timing.stats()['push attachment']['slow'], 0)

    async def test_terminal_push_is_timed_from_enqueue_to_send(self):
        registry = TerminalViewerRegistry(lambda: '')
        viewer = registry.attach()
        registry.publish(b'bytes')
        self.clock.advance(0.4)  # the loop was busy before the sender ran
        authority = MagicMock(require=AsyncMock(side_effect=[True, True, False]))
        ws = MagicMock(send_bytes=AsyncMock())
        with self.logged() as logs:
            await _send_terminal(ws, viewer, authority)
        ws.send_bytes.assert_awaited_once_with(b'bytes')
        self.assertEqual(len(logs.output), 1)
        self.assertIn('push terminal took 400 ms', logs.output[0])
        stat = op_timing.stats()['push terminal']
        self.assertEqual((stat['count'], stat['slow']), (1, 1))


class EveryPushTest(TimingCase):
    async def test_slow_failing_chat_push_is_recorded_flagged_and_dropped(self):
        async def send(payload):
            self.clock.advance(0.5)
            raise ConnectionError

        socket = MagicMock(send_json=send)
        runtime = MagicMock(sockets={'line': {socket}}, human_handles={})
        with self.logged() as logs:
            await push_event(runtime, 'line', {'type': 'message'})
        self.assertEqual(runtime.sockets['line'], set())
        self.assertIn('push message', logs.output[0])
        self.assertEqual(op_timing.stats()['push message']['slow'], 1)

    async def test_slow_failing_terminal_send_is_recorded(self):
        registry = TerminalViewerRegistry(lambda: '')
        viewer = registry.attach()
        registry.publish(b'x')
        self.clock.advance(0.3)
        authority = MagicMock(require=AsyncMock(return_value=True))
        ws = MagicMock(send_bytes=AsyncMock(side_effect=ConnectionError))
        with self.logged(), self.assertRaises(ConnectionError):
            await _send_terminal(ws, viewer, authority)
        stat = op_timing.stats()['push terminal']
        self.assertEqual((stat['count'], stat['slow']), (1, 1))

    async def test_screen_event_push_is_timed(self):
        async def send(payload):
            self.clock.advance(0.5)

        hub = SimpleNamespace(shares={}, runtime=SimpleNamespace(
            sockets={'line': {MagicMock(send_json=send)}}))
        with self.logged() as logs:
            await ScreenHub._line_event(hub, 'line', {'type': 'screen'})
        self.assertIn('push screen', logs.output[0])
        self.assertEqual(op_timing.stats()['push screen']['slow'], 1)

    async def test_failed_screen_send_is_still_recorded(self):
        async def send(payload):
            self.clock.advance(0.5)
            raise RuntimeError

        hub = SimpleNamespace(shares={}, runtime=SimpleNamespace(
            sockets={'line': {MagicMock(send_json=send)}}))
        with self.logged():
            await ScreenHub._line_event(hub, 'line', {'type': 'screen'})
        self.assertEqual(op_timing.stats()['push screen']['slow'], 1)

    async def test_every_websocket_send_in_the_package_is_timed(self):
        untimed = []
        for path in (ROOT / 'partyline').rglob('*.py'):
            lines = path.read_text().splitlines()
            for number, line in enumerate(lines):
                if '.send_json(' in line or '.send_text(' in line or '.send_bytes(' in line:
                    window = ' '.join(lines[max(0, number - 1):number + 1])
                    if 'pushed(' not in window and path.name not in ('ws_push.py', 'terminal_stream.py'):
                        untimed.append(f'{path.name}:{number + 1}')
        self.assertEqual(untimed, [])


class DispatchTest(TimingCase):
    make = v2_tests.OpenCodeV2Tests.make
    row = v2_tests.OpenCodeV2Tests.row
    claim = v2_tests.OpenCodeV2Tests.claim

    def setUp(self):
        super().setUp()
        v2_tests.OpenCodeV2Tests.setUp(self)

    def slow(self, seconds=0.5):
        async def call(*args, **kwargs):
            self.clock.advance(seconds)
        return call

    async def test_opencode_v2_speech_dispatch_is_timed(self):
        self.adapter._post_to_chat = self.slow()
        self.claim()
        self.row('answer', 'assistant', {
            'time': {'completed': 2}, 'content': [{'type': 'text', 'text': SECRET}]}, seq=2)
        with self.logged() as logs:
            await self.adapter._poll()
        self.assertEqual(len(logs.output), 1)
        self.assertIn('dispatch adapter post took 500 ms', logs.output[0])
        self.assertNotIn(SECRET, logs.output[0])

    async def test_opencode_v2_compaction_callback_is_timed(self):
        self.adapter.att['on_compaction'] = self.slow()
        self.claim()
        self.row('compact', 'compaction', dict(v2_tests.OpenCodeV2Tests.COMPACTION), seq=2)
        with self.logged() as logs:
            await self.adapter._poll()
        self.assertIn('dispatch adapter on_compaction took 500 ms', logs.output[0])

    async def test_resume_backlog_callback_is_timed(self):
        self.adapter.att['post_resume_record'] = self.slow()
        with self.logged() as logs:
            await self.adapter.att['post_resume_record']('agent', 'agent', 'old words')
        self.assertIn('dispatch adapter post_resume_record', logs.output[0])

    async def test_synchronous_callbacks_and_failures_are_timed_too(self):
        att = op_timing.TimedAtt({'adapter': 'x', 'mark_transcript_delivery':
                                  lambda *a: self.clock.advance(0.3)})
        with self.logged():
            att['mark_transcript_delivery']('fp', 'body')
        failing = op_timing.callback({'adapter': 'x'}, 'on_status', AsyncMock(
            side_effect=lambda *a: self.clock.advance(0.3)))

        async def raise_after(*args):
            self.clock.advance(0.3)
            raise RuntimeError

        with self.logged(), self.assertRaises(RuntimeError):
            await op_timing.callback({'adapter': 'x'}, 'on_status', raise_after)('running')
        self.assertEqual(op_timing.stats()['dispatch x mark_transcript_delivery']['slow'], 1)
        self.assertEqual(op_timing.stats()['dispatch x on_status']['slow'], 1)
        self.assertIs(op_timing.callback({}, 'k', failing), failing)  # never wrapped twice

        def explode(*args):
            self.clock.advance(0.3)
            raise ValueError

        with self.logged(), self.assertRaises(ValueError):
            op_timing.callback({'adapter': 'x'}, 'on_cli_session', explode)('id')
        self.assertEqual(op_timing.stats()['dispatch x on_cli_session']['slow'], 1)

    async def test_every_bundled_adapter_dispatches_through_the_timed_callbacks(self):
        load_bundled_adapters()
        kinds = sorted(path.parent.name for path in BUNDLED_ROOT.glob('*/adapter.toml'))
        self.assertGreater(len(kinds), 5)
        for kind in kinds:
            att = dict(id='a', name='agent', conv_id='line', conv='room', cwd='/project',
                       command=[], adapter=kind)
            att.update({key: self.slow() for key in op_timing.CALLBACK_KEYS})
            adapter = make_adapter(kind, att, self.slow(), self.slow(), self.slow())
            self.assertIs(type(adapter), ADAPTERS[kind], kind)
            op_timing.reset()
            with self.logged():
                await adapter._post_to_chat('agent', 'agent', 'x')
                await adapter.on_status('running')
                await adapter.on_cli_session('session')
                for key in op_timing.CALLBACK_KEYS:
                    await adapter.att[key]()
            wanted = {f'dispatch {kind} {key}' for key in
                      ('post', 'on_status', 'on_cli_session', *op_timing.CALLBACK_KEYS)}
            self.assertEqual({name for name, stat in op_timing.stats().items() if stat['slow']}, wanted)

    def test_bundled_adapters_only_call_back_through_registered_keys(self):
        import re
        pattern = re.compile(r"att(?:\.get\(|\[)\s*[\"']((?:on|post|confirm|credit|repool|mark)_\w+)[\"']")
        for path in BUNDLED_ROOT.rglob('*.py'):
            text = path.read_text()
            for key in pattern.findall(text):
                self.assertIn(key, op_timing.CALLBACK_KEYS, f'{path.name} calls {key} untimed')
            self.assertNotIn('runtime.post_message', text, path.name)
            self.assertNotIn('runtime.broadcast', text, path.name)


class IdleTest(TimingCase):
    async def test_idle_server_schedules_nothing(self):
        loop = asyncio.get_running_loop()
        tasks, threads = len(asyncio.all_tasks()), threading.active_count()

        def refuse(*args, **kwargs):
            raise AssertionError('idle path created a timer')

        with patch.object(loop, 'call_later', refuse), patch.object(loop, 'call_at', refuse), \
                patch.object(threading.Thread, 'start', refuse), patch('threading.Timer', refuse):
            self.app()
            op_timing.register_stack_dump()
        self.assertEqual(loop._scheduled, [])
        self.assertEqual((len(asyncio.all_tasks()), threading.active_count()), (tasks, threads))

    def test_module_source_has_no_timer_or_sleep(self):
        for name in ('op_timing', 'ws_push'):
            source = (ROOT / 'partyline' / f'{name}.py').read_text()
            for forbidden in ('sleep', 'create_task', 'call_later', 'Timer', 'Thread', 'while True'):
                self.assertNotIn(forbidden, source, f'{name} must not use {forbidden}')

    def test_stack_dump_is_a_signal_handler_where_the_platform_has_one(self):
        import signal
        with patch('faulthandler.register') as register:
            self.assertTrue(op_timing.register_stack_dump())
        self.assertEqual(register.call_args.args[0], signal.SIGUSR1)
        self.assertTrue(register.call_args.kwargs['all_threads'])
        with patch('faulthandler.register', side_effect=OSError):
            self.assertFalse(op_timing.register_stack_dump())
        with patch.object(op_timing.signal, 'SIGUSR1', create=True, new=None):
            del op_timing.signal.SIGUSR1
            self.assertFalse(op_timing.register_stack_dump())


class SettingsTest(unittest.TestCase):
    def test_settings_reject_invalid_values(self):
        import os
        for bad in ('nan', 'bad', '-1'):
            with patch.dict(os.environ, {'TEST_SLOW': bad}):
                self.assertEqual(op_timing._setting('TEST_SLOW', 0.25, 0), 0.25)
        with patch.dict(os.environ, {'TEST_SLOW': '0.5'}):
            self.assertEqual(op_timing._setting('TEST_SLOW', 0.25, 0), 0.5)


class OldConsumersTest(unittest.TestCase):
    def test_probe_watchdog_and_attribution_modules_are_gone(self):
        for name in ('event_loop_lag', 'loop_watchdog', 'periodic_timing'):
            self.assertIsNone(importlib.util.find_spec(f'partyline.{name}'), name)

    def test_nothing_reads_the_old_lag_numbers_or_settings(self):
        stale = ('event_loop_lag', 'loop_watchdog', 'periodic_timing', 'LOOP_LAG', 'LOOP_WATCHDOG',
                 'timed_tick', 'monitor_event_loop')
        for root in ('partyline', 'scripts', 'docs', 'frontend/src'):
            for path in (ROOT / root).rglob('*'):
                if not path.is_file() or path.suffix not in ('.py', '.md', '.ts', '.svelte'):
                    continue
                text = path.read_text()
                for word in stale:
                    if path.name in ('lessons.md', 'polling-audit.md') and word in (
                            'event_loop_lag', 'loop_watchdog'):
                        continue  # the history names what it removed
                    self.assertFalse(word in text, f'{path.relative_to(ROOT)} still mentions {word}')

    def test_server_times_requests_and_registers_the_stack_signal(self):
        source = (ROOT / 'partyline' / 'server.py').read_text()
        self.assertIn('op_timing.install(app)', source)
        self.assertIn('op_timing.register_stack_dump()', source)

    def test_polling_guard_has_no_loop_lag_exceptions(self):
        from scripts import no_polling
        self.assertFalse([key for key in no_polling.UNRESOLVED if 'lag' in key[0]])
