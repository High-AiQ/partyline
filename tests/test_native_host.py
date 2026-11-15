"""Native broker authenticated IPC with fake streams and no live ports."""
import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper import native_host, native_windows
from partyline_helper.chrome_identity import ORIGIN
from partyline_helper.native_codec import frame, read_frame
from partyline_helper.native_socket import NativeSocket


class Writer:
    def __init__(self):
        self.output = io.BytesIO()
        self.closed = False
    def write(self, raw):
        self.output.write(raw)
    async def drain(self):
        pass
    def close(self):
        self.closed = True
    async def wait_closed(self):
        pass


def reader(*messages):
    r = asyncio.StreamReader()
    for message in messages:
        r.feed_data(frame(message))
    r.feed_eof()
    return r


class NativeHostTests(unittest.IsolatedAsyncioTestCase):
    async def test_socket_large_messages_eof_and_synchronous_revoke(self):
        w = Writer()
        s = NativeSocket(reader({"id": 1}), w)
        self.assertEqual(json.loads(await anext(s)), {"id": 1})
        with self.assertRaises(StopAsyncIteration):
            await anext(s)
        s.send_nowait({"method": "Partyline.revoke", "grant": "g"})
        w.output.seek(0)
        self.assertEqual(read_frame(w.output)["method"], "Partyline.revoke")
        await s.send(json.dumps({"value": "a" * 400000}))
        await s.close()
        self.assertTrue(w.closed)

    async def test_authenticated_bridge_rejects_wrong_secret_and_duplicate_peer(self):
        output, writer = io.BytesIO(), Writer()
        bridge = native_host.Bridge(output, "secret", browser_pid=12)
        await bridge.accept(reader({"token": "wrong"}), writer)
        self.assertTrue(writer.closed)
        self.assertEqual(output.getvalue(), b"")
        bridge.client = object()
        await bridge.accept(reader({"token": "secret"}), Writer())
        self.assertEqual(output.getvalue(), b"")
        bridge.client = None
        await bridge.accept(reader({"token": "secret"}, {"id": 1, "method": "DOM.enable"}), Writer())
        output.seek(0)
        self.assertEqual(read_frame(output)["method"], "DOM.enable")
        self.assertEqual(read_frame(output)["method"], "Partyline.reset")
        self.assertIsNone(bridge.client)
        await bridge.accept(reader(), Writer())
        await bridge.accept(reader([]), Writer())

    async def test_receive_stamps_actual_chrome_parent_pid_and_forwards_events(self):
        bridge = native_host.Bridge(io.BytesIO(), "secret", browser_pid=12)
        w = Writer()
        bridge.client = NativeSocket(reader(), w)
        bridge.pending[1] = (bridge.client, 55)
        stream = io.BytesIO(frame({"id": 1, "result": {}}) + frame({"method": "Inspector.targetCrashed"}))
        await bridge.receive(stream)
        w.output.seek(0)
        response = read_frame(w.output)
        self.assertEqual(response["id"], 55)
        self.assertEqual(response["result"]["_partyline_browser_pid"], 12)
        self.assertEqual(read_frame(w.output)["method"], "Inspector.targetCrashed")
        bridge.client = None
        await bridge.receive(io.BytesIO(frame({"id": 2})))
        await bridge.receive(io.BytesIO(b"bad"))

    async def test_host_lifecycle_writes_private_discovery_and_cleans_it(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "native.json"
            server = Mock(sockets=[Mock(getsockname=lambda: ("127.0.0.1", 1234))],
                          wait_closed=AsyncMock())
            async def receive(bridge, stream):
                self.assertEqual(native_host.discover()["port"], 1234)
                bridge.client = NativeSocket(reader(), Writer())
            with patch.object(native_host, "endpoint_path", return_value=path), \
                    patch.object(native_host.asyncio, "start_server", AsyncMock(return_value=server)), \
                    patch.object(native_host.Bridge, "receive", receive), \
                    patch.object(native_host, "InstanceLock") as lock:
                lock.return_value.acquire.return_value = True
                path.with_name("chrome-native.pid").write_text(str(os.getpid()))
                await native_host.run(io.BytesIO(), io.BytesIO())
                self.assertFalse(path.exists())
                lock.return_value.release.assert_called_once()
                lock.return_value.acquire.return_value = False
                await native_host.run(io.BytesIO(), io.BytesIO())

    async def test_discovery_and_main_origin_validation(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "native.json"
            with patch.object(native_host, "endpoint_path", return_value=path):
                self.assertIsNone(native_host.discover())
                for value in ('bad', '{}', '{"port":0,"token":"x"}',
                              '{"port":1234,"token":1}'):
                    path.write_text(value)
                    self.assertIsNone(native_host.discover())
                path.write_text(json.dumps({"port": 1234, "token": "a" * 64, "pid": 12}))
                path.with_name("chrome-native.pid").write_text("12")
                with patch.object(native_host, "wait_pid", return_value=False) as wait:
                    self.assertEqual(native_host.discover()["port"], 1234)
                    wait.return_value = True
                    self.assertIsNone(native_host.discover())
        for args in ([], ['chrome-extension://evil/']):
            with self.assertRaises(ValueError):
                native_host.main(args)
        with patch.object(native_host, "run", Mock(return_value='work')), \
                patch.object(native_host.asyncio, "run") as runner:
            native_host.main([ORIGIN], io.BytesIO(), io.BytesIO())
            runner.assert_called_once_with('work')
        with patch.object(native_windows, "sys") as system, \
                patch.object(native_windows, "os") as operating, \
                patch.dict('sys.modules', {'msvcrt': Mock()}) as modules:
            system.stdin.fileno.return_value = 3
            system.stdout.fileno.return_value = 4
            operating.O_BINARY = 32768
            native_windows.binary_stdio()
            self.assertEqual(modules['msvcrt'].setmode.call_count, 2)

    async def test_previous_helpers_late_response_cannot_complete_new_helpers_call(self):
        bridge = native_host.Bridge(io.BytesIO(), 'secret', browser_pid=12)
        current = NativeSocket(reader(), Writer())
        bridge.client = current
        bridge.pending[2] = (current, 1)
        bridge.pending[3] = (object(), 2)
        await bridge.receive(io.BytesIO(frame({'id': 1, 'result': {'old': True}})
                                       + frame({'id': 3, 'result': {'wrong_owner': True}})
                                       + frame({'id': 2, 'result': {'fresh': True}})))
        current.writer.output.seek(0)
        response = read_frame(current.writer.output)
        self.assertEqual(response['id'], 1)
        self.assertTrue(response['result']['fresh'])
        with self.assertRaises(EOFError):
            read_frame(current.writer.output)

    async def test_windows_source_launchers_and_cmd_intermediary_resolve_chrome_ancestor(self):
        import ctypes
        from types import SimpleNamespace
        def snapshot(rows):
            remaining = iter(rows)
            def advance(handle, pointer):
                try:
                    pid, parent, name = next(remaining)
                except StopIteration:
                    return 0
                pointer._obj.pid, pointer._obj.parent, pointer._obj.exe = pid, parent, name
                return 1
            return SimpleNamespace(CreateToolhelp32Snapshot=Mock(return_value=1), CloseHandle=Mock(),
                                   Process32FirstW=Mock(side_effect=advance),
                                   Process32NextW=Mock(side_effect=advance))
        kernel = snapshot([(100, 99, 'python.exe'), (99, 98, 'partyline-chrome-host.exe'),
                           (98, 12, 'cmd.exe'), (12, 1, 'CHROME.EXE')])
        self.assertEqual(native_windows.chrome_parent(kernel, 100), 12)
        kernel.CloseHandle.assert_called_once_with(1)
        for rows in ([], [(100, 0, 'python.exe')], [(100, 100, 'loop.exe')]):
            self.assertEqual(native_windows.chrome_parent(snapshot(rows), 100), 0)
        kernel = snapshot([])
        kernel.CreateToolhelp32Snapshot.return_value = ctypes.c_void_p(-1).value
        self.assertEqual(native_windows.chrome_parent(kernel, 100), 0)
        kernel.CloseHandle.assert_not_called()
        with patch.object(native_host.sys, 'platform', 'win32'), \
                patch.object(native_windows, 'chrome_parent', return_value=12):
            self.assertEqual(native_host.Bridge(io.BytesIO(), 'secret').browser_pid, 12)
        with patch.object(native_host.sys, 'platform', 'win32'), \
                patch.object(native_windows, 'binary_stdio') as binary, \
                patch.object(native_host, 'run', Mock(return_value='work')), \
                patch.object(native_host.asyncio, 'run'):
            native_host.main([ORIGIN], io.BytesIO(), io.BytesIO())
            binary.assert_called_once()

    async def test_pre_auth_input_is_one_small_unchunked_frame(self):
        import struct
        for payload in (struct.pack('=I', 1025), frame({'chunk': {'index': 0, 'total': 2, 'data': '{}'}})):
            stream = asyncio.StreamReader()
            stream.feed_data(payload)
            stream.feed_eof()
            output, writer = io.BytesIO(), Writer()
            bridge = native_host.Bridge(output, 'secret', browser_pid=12)
            await bridge.accept(stream, writer)
            self.assertIsNone(bridge.client)
            self.assertEqual(output.getvalue(), b'')
            self.assertTrue(writer.closed)

    async def test_discovery_requires_a_live_pid_not_a_stale_endpoint(self):
        from partyline_helper.instance import InstanceLock
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            endpoint = directory / 'native.json'
            endpoint.write_text(json.dumps({'port': 1234, 'token': 'a' * 64, 'pid': os.getpid()}))
            with patch.object(native_host, 'endpoint_path', return_value=endpoint), \
                    patch('partyline_helper.instance.lock_dir', return_value=directory):
                self.assertIsNone(native_host.discover())
                with InstanceLock('chrome-native', directory) as host:
                    self.assertIsNotNone(host)
                    self.assertEqual(native_host.discover()['port'], 1234)
                self.assertIsNone(native_host.discover())

    async def test_discovery_cannot_take_the_lock_while_chrome_starts_a_host(self):
        from partyline_helper.instance import InstanceLock
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            endpoint = directory / 'native.json'
            pid_path = directory / 'chrome-native.pid'
            endpoint.write_text(json.dumps({'port': 1234, 'token': 'a' * 64, 'pid': 42}))
            pid_path.write_text('42')
            host = InstanceLock('chrome-native', directory)
            started = []
            def old_process_exited(pid, timeout):
                self.assertEqual((pid, timeout), (42, 0))
                started.append(host.acquire())
                return True
            try:
                with patch.object(native_host, 'endpoint_path', return_value=endpoint), \
                        patch.object(native_host, 'wait_pid', side_effect=old_process_exited):
                    self.assertIsNone(native_host.discover())
                self.assertEqual(started, [True])
                self.assertEqual(pid_path.read_text(), str(os.getpid()))
                with patch.object(native_host, 'endpoint_path', return_value=endpoint), \
                        patch.object(native_host, 'wait_pid', return_value=False), \
                        patch.object(native_host, 'InstanceLock', side_effect=AssertionError('lock probe')):
                    # The previous host's endpoint must not be paired with this host's live PID.
                    self.assertIsNone(native_host.discover())
                    endpoint.write_text(json.dumps({'port': 5678, 'token': 'b' * 64, 'pid': os.getpid()}))
                    self.assertEqual(native_host.discover()['port'], 5678)
                    self.assertEqual(pid_path.read_text(), str(os.getpid()))
                for value in ('invalid', '-1', str(2 ** 40)):
                    pid_path.write_text(value)
                    with patch.object(native_host, 'endpoint_path', return_value=endpoint):
                        self.assertIsNone(native_host.discover())
            finally:
                host.release()
