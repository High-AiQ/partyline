"""Fake time through actual server exchanges, helper scheduling, child readiness and reply queueing."""
import asyncio
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline import screen_timing
from partyline.screen_elements import ElementsHub
from partyline_helper.session_transport import SessionTransport
from partyline_helper.timing import Timing
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_process import read
from partyline_helper.uia_task import WindowTask
from tests.test_screen_latency import Clock


class ServerTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_roundtrip_helper_and_window_lock_phases(self):
        clock = Clock()
        hub = ElementsHub(SimpleNamespace())
        device = {'id': 'd', 'socket': SimpleNamespace()}
        async def send(message):
            clock.advance(5)
            def deliver():
                clock.advance(9)
                hub.receive(device, {'request_id': message['request_id'], 'timing': {'uia_ms': 7}})
            asyncio.get_running_loop().call_soon(deliver)
        device['socket'].send_json = send
        class Lock:
            async def acquire(self):
                clock.advance(2)
            def release(self):
                clock.advance(1)
        hub.locks['g'] = [Lock(), 0]
        @screen_timing.timed
        async def operation():
            async with hub.locked('g'):
                return await hub.exchange(SimpleNamespace(), {'id': 'g'}, device, 'read_window_elements')
        with patch.object(screen_timing, 'clock', clock), patch('partyline.screen_elements.require_window'):
            result = await operation()
        self.assertEqual({'request_queue_ms': 0, 'window_lock_ms': 2, 'send_ms': 5,
                          'helper_roundtrip_ms': 9, 'helper_uia_ms': 7, 'server_total_ms': 17},
                         result['timing'])
        self.assertFalse(hub.locks)
        self.assertFalse(hub.waiters)


class HelperTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_window_checks_worker_queue_and_task_queue_use_fake_time(self):
        clock = Clock()
        grant = {'hwnd': 1, 'pid': 2, 'title': 'App', 'process': 'app'}
        session = SimpleNamespace(share=None, accepted=False, send=AsyncMock())
        access = WindowAccess(session, platform='win32')
        access.grant = grant
        session.window = access
        async def check(_):
            clock.advance(2)
        def reader(*args, **kwargs):
            clock.advance(5)
            return {'elements': [], 'snapshot_id': 's'}
        access.check, access.reader = check, reader
        async def thread(function, *args, **kwargs):
            clock.advance(3)
            return function(*args, **kwargs)
        with patch('partyline_helper.timing.clock', clock), \
                patch('partyline_helper.uia_access.asyncio.to_thread', thread):
            queued = Timing()
            clock.advance(4)
            await WindowTask(session)._read('r', queued=queued)
        timing = session.send.await_args.kwargs['timing']
        self.assertEqual({'task_queue_ms': 4, 'window_check_ms': 4, 'worker_queue_ms': 3,
                          'read_ms': 12}, timing)

    async def test_reply_time_includes_writer_queue_and_final_gate(self):
        clock = Clock()
        class Lock:
            async def __aenter__(self):
                clock.advance(3)
            async def __aexit__(self, *args):
                pass
        session = SessionTransport()
        session.lock, session.socket = Lock(), SimpleNamespace(send=AsyncMock())
        async def gate():
            clock.advance(2)
        with patch('partyline_helper.timing.clock', clock):
            await session.send('window_elements', before=gate, timing={'walk_ms': 1})
        packet = json.loads(session.socket.send.await_args.args[0])
        self.assertEqual({'walk_ms': 1, 'reply_ms': 5}, packet['timing'])

    def test_child_launch_initialization_walk_and_reply_fake_clock(self):
        clock = Clock()
        def popen(command, **kwargs):
            clock.advance(2)
            Path(json.loads(command[-1])[2]).write_text('{"elements": []}', encoding='utf-8')
            def wait(**kwargs):
                clock.advance(5)
            return SimpleNamespace(stdout=io.BytesIO(b'READY\n'), wait=wait,
                                   poll=lambda: 0, returncode=0)
        def ready(timeout):
            clock.advance(3)
            return True
        with patch('partyline_helper.timing.clock', clock):
            result = read(1, popen=popen, platform='win32', ready_wait=ready)
        self.assertEqual({'process_start_ms': 2, 'initialize_ms': 3,
                          'child_read_ms': 5, 'reply_ms': 0}, result['timing'])

    async def test_action_audit_and_worker_queue_use_fake_time(self):
        from partyline_helper.uia_action_worker import ActionWorker
        from partyline_helper.uia_gate import DispatchGate
        clock, gate = Clock(), DispatchGate()
        gate.grant()
        audit = SimpleNamespace(ensure_writable=lambda: clock.advance(2), append=Mock())
        access = SimpleNamespace(grant={'hwnd': 1}, gate=gate, elements={'id': {'name': 'field'}})
        session = SimpleNamespace(window=access, window_grant_id='g', tools=SimpleNamespace(audit=audit))
        async def thread(function, *args, **kwargs):
            return function(*args, **kwargs)
        def spawn(function):
            clock.advance(3)
            future = asyncio.get_running_loop().create_future()
            future.set_result(function())
            return future
        def runner(*args):
            clock.advance(5)
            return {'status': 'completed'}
        with patch('partyline_helper.timing.clock', clock), \
                patch('partyline_helper.uia_action_worker.asyncio.to_thread', thread), \
                patch('partyline_helper.uia_action_worker.spawn_worker', spawn):
            message = {'element_id': 'id', 'action': 'invoke'}
            result = await ActionWorker(session, runner=runner).perform(message)
        self.assertEqual({'audit_ms': 2, 'worker_queue_ms': 3, 'action_total_ms': 10}, result['timing'])

    async def test_screenshot_capture_encoding_and_storage_phases_use_fake_time(self):
        from partyline_helper.window_snapshot import WindowSnapshots
        from partyline.screen_window_snapshot import WindowSnapshots as ServerSnapshots
        clock, packets = Clock(), []
        grant = {'hwnd': 1, 'title': 'App', 'process': 'app'}
        gate = DispatchGate()
        gate.grant()
        access = SimpleNamespace(grant=grant, generation=1, check=AsyncMock(return_value=None), gate=gate)
        async def send(*args, **kwargs):
            packets.append(kwargs)
        shares = SimpleNamespace(session=SimpleNamespace(send=send), changed=Mock())
        backend = SimpleNamespace(minimized=lambda _: False,
                                  grab=lambda _: clock.advance(5) or SimpleNamespace(width=1, height=1,
                                                                          info={}))
        async def thread(function, *args):
            return function(*args)
        def encode(image):
            clock.advance(7)
            return b'image', 'image/png', False
        with patch('partyline_helper.timing.clock', clock), \
                patch('partyline_helper.window_snapshot.asyncio.to_thread', thread), \
                patch('partyline_helper.window_snapshot.prepare', encode):
            await WindowSnapshots(shares, backend).take({'access': access}, {'agent': 'a'}, 'r')
        self.assertEqual({'capture_ms': 5, 'encode_ms': 7}, packets[0]['timing'])
        async def exchange(*args, **kwargs):
            return {'ok': True, 'timing': {}}
        hub = SimpleNamespace(elements=SimpleNamespace(exchange=exchange))
        snapshots = ServerSnapshots(hub)
        async def keep(*args):
            clock.advance(9)
            return {}
        snapshots.keep = keep
        resolved = ({'id': 'g'}, {'windows': 2})
        with patch.object(screen_timing, 'clock', clock), \
                patch('partyline.screen_window_snapshot.resolve_window', return_value=resolved):
            result = await snapshots.take(SimpleNamespace(name='a'), None)
        self.assertEqual(9, result['timing']['image_store_ms'])

    def test_live_inspect_separates_target_resolution_from_observation(self):
        from partyline_helper.uia_probe import inspect
        clock = Clock()
        def find(*args):
            clock.advance(3)
            return 'node'
        def observe(*args):
            clock.advance(7)
            return {'ancestors': [{}], 'live': {'enabled': True}}
        with patch('partyline_helper.timing.clock', clock), \
                patch('partyline_helper.uia_probe.find', find), \
                patch('partyline_helper.uia_probe._inspect', observe):
            result = inspect(SimpleNamespace(com_calls=5), 'id')
        self.assertEqual({'target_ms': 3, 'post_read_ms': 7, 'nodes': 2, 'com_calls': 5, 'total_ms': 10},
                         result['timing'])
