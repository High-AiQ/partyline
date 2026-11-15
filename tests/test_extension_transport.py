"""The production provider consumes framed native CDP without page API changes."""
import asyncio
import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline_helper import chrome_operations
from partyline_helper.cdp_transport import BrowserConnection, CDPError
from partyline_helper.extension_transport import ExtensionTransport
from tests.extension_fakes import fixture


class ExtensionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f, self.peer = fixture()
        self.addAsyncCleanup(self.f.close)

    async def test_prefer_extension_read_grant_scope_operation_and_status(self):
        result = await self.f.read()
        self.assertEqual(result['transport'], 'extension')
        self.assertEqual(result['source'], 'cdp')
        scope = next(m for m in self.peer.calls if m['method'] == 'Partyline.scope')
        self.assertEqual(scope['grant'], 'g')
        self.assertEqual(scope['params']['tabs'], [1, 2])
        methods = [m['method'] for m in self.peer.calls]
        self.assertLess(methods.index('Partyline.begin'), methods.index('Target.attachToTarget'))
        self.assertEqual(methods[-1], 'Partyline.end')
        self.assertEqual(self.f.session.status.chrome, 'Chrome: extension connected')
        await self.f.chrome.publish('connected', '')
        self.assertEqual(self.f.session.send.call_args.kwargs['transport'], 'extension')
        tabs = await self.f.chrome.tabs(self.f.access)
        self.assertEqual([t['target_id'] for t in tabs], ['1', '2'])
        self.assertEqual([t['target_id'] for t in tabs if t['active']], ['1'])
        self.f.access.grant['target_id'] = '1'
        await self.f.read()
        self.assertEqual(next(m for m in reversed(self.peer.calls)
                              if m['method'] == 'Partyline.scope')['params']['tabs'], [1])

    async def test_flat_sessions_large_ax_trees_and_crash_event_relay(self):
        await self.f.read()
        events = []
        self.f.browser.listeners.add(events.append)
        await self.f.browser.call('DOM.enable', session='child')
        self.assertEqual(self.peer.raw_calls[-1]['sessionId'], 'child')
        self.peer.feed({'method': 'Inspector.targetCrashed', 'sessionId': 'child', 'params': {}})
        await self.f.browser.call('Browser.getVersion')  # protocol fence, no wall-clock wait
        self.assertEqual(events[-1]['sessionId'], 'child')
        self.f.socket.nodes = [dict(nodeId='1', name={'value': 'x' * 400000}, role={'value': 'text'})]
        result = await self.f.browser.call('Accessibility.getFullAXTree', session='g:1')
        self.assertEqual(len(result['nodes'][0]['name']['value']), 400000)

    async def test_revoke_is_written_synchronously_and_no_later_page_command(self):
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        self.f.chrome.revoke(self.f.access)
        self.assertTrue(self.peer.revoked)
        self.assertFalse(self.f.browser.grants)
        with self.assertRaises(CDPError):
            await page.call('Input.dispatchKeyEvent')
        with self.assertRaises(CDPError):
            await self.f.browser.call('Target.attachToTarget', {'targetId': '1'})

    async def test_resume_reinitializes_same_document_and_invalidates_changed_document(self):
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        old_nodes = dict(page.nodes)
        before = self.f.chrome.status(self.f.access)['event_counter']
        self.peer.resumed = {'reattached': True, 'documentChanged': False}
        await self.f.chrome.page(self.f.access)
        self.assertTrue(page.initialized)
        self.assertEqual(page.nodes, old_nodes)
        self.assertGreater(self.f.chrome.status(self.f.access)['event_counter'], before)
        self.peer.resumed = {'reattached': True, 'documentChanged': True}
        await self.f.chrome.page(self.f.access)
        self.assertFalse(page.nodes)
        self.assertEqual(page.epoch, 1)
        page.frames = {'child': object()}
        page.drop_frame = Mock(side_effect=lambda key: page.frames.pop(key))
        self.peer.resumed = {'reattached': True}
        await self.f.browser.resume(page)
        page.drop_frame.assert_called_once_with('child')

    async def test_process_ambiguity_and_missing_native_window_refuse_mapping(self):
        await self.f.browser.ensure()
        self.peer.pid = 99
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        self.assertIn('process', self.f.chrome.reasons[self.f.access])
        self.peer.pid, self.peer.ambiguous = 12, True
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        self.assertIn('ambiguous', self.f.chrome.reasons[self.f.access])
        self.f.access.list_windows = lambda: []
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        self.assertIn('closed', self.f.chrome.reasons[self.f.access])

    async def test_absent_extension_uses_explicit_remote_debugging_fallback(self):
        self.f.browser.opener.side_effect = OSError('absent')
        self.f.chrome.auto_transport = True
        with patch.object(chrome_operations, 'discover', return_value=None), \
                patch('partyline_helper.cdp_transport.discover', return_value=None):
            await self.f.chrome.read(self.f.access, {}, {})
        self.assertEqual(self.f.chrome.browser.transport, 'remote_debugging')
        self.assertIn('remote debugging fallback', self.f.chrome.browser.detail)

    async def test_default_selection_and_late_extension_replaces_remote(self):
        with patch.object(chrome_operations, 'discover', return_value=None):
            self.assertIsInstance(chrome_operations.preferred(Mock()), BrowserConnection)
        with patch.object(chrome_operations, 'discover', return_value={'port': 1234}):
            self.assertIsInstance(chrome_operations.preferred(Mock()), ExtensionTransport)
            self.f.chrome.auto_transport = True
            original = self.f.chrome.browser = BrowserConnection()
            browser = await chrome_operations.select_extension(self.f.chrome)
            self.assertTrue(original.closed)
            self.assertIsInstance(browser, ExtensionTransport)

    async def test_watch_installs_without_polling_and_cancels_cleanly(self):
        entered = asyncio.Event()
        @contextlib.asynccontextmanager
        async def events(path):
            async def wait():
                entered.set()
                await asyncio.Event().wait()
            yield SimpleNamespace(wait=wait)
        with patch.object(chrome_operations, 'discover', return_value={'port': 1234}):
            task = asyncio.create_task(chrome_operations.watch_extension(self.f.chrome, events))
            await entered.wait()
            self.assertEqual(self.f.browser.state, 'connected')
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        @contextlib.asynccontextmanager
        async def broken(path):
            raise OSError('notifications missing')
            yield
        await chrome_operations.watch_extension(self.f.chrome, broken)

    async def test_operation_does_not_retry_commands_on_transport_failure(self):
        self.f.browser.opener.side_effect = OSError('closed')
        with self.assertRaises(CDPError):
            async with self.f.browser.operation(self.f.access):
                self.fail('must not dispatch')
        self.f.browser.revoke(self.f.access)

    async def test_detach_notification_stops_page(self):
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        self.peer.feed({'method': 'Target.detachedFromTarget', 'params': {'sessionId': page.session}})
        await self.f.browser.call('Browser.getVersion')
        self.assertEqual(page.page_state, "detached")

    async def test_idle_attachment_state_does_not_claim_live_cdp_events(self):
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        self.assertTrue(self.f.browser.is_attached(page.session))
        self.peer.feed({'method': 'Partyline.attachment', 'sessionId': page.session,
                        'params': {'attached': False}})
        await self.f.browser.call('Browser.getVersion')
        self.assertFalse(self.f.browser.is_attached(page.session))
        self.assertFalse(self.f.chrome.status(self.f.access)['subscription_live'])
        with patch.object(self.f.browser.socket, 'send_nowait', side_effect=OSError('closed')):
            self.f.chrome.revoke(self.f.access)
        self.assertFalse(page.live)

    async def test_cancelled_operation_begin_always_releases_its_lease(self):
        await self.f.browser.ensure()
        entered, calls = asyncio.Event(), []
        async def control(method, **kwargs):
            calls.append(method)
            if method == 'Partyline.begin':
                entered.set()
                await asyncio.Event().wait()
        async def operate():
            async with self.f.browser.operation(self.f.access):
                self.fail('cancelled before entering')
        with patch.object(self.f.browser, 'control', control):
            task = asyncio.create_task(operate())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(calls, ['Partyline.begin', 'Partyline.end'])

    async def test_invisible_profile_or_incognito_duplicate_hwnd_refuses_mapping(self):
        # The extension can see one window while the native list sees two from the same browser PID.
        for title in ('Lab - Google Chrome', 'Lab - Other profile - Google Chrome'):
            with self.subTest(caption=title):
                duplicate = {**self.f.window, 'hwnd': 2, 'title': title}
                self.f.access.list_windows = lambda duplicate=duplicate: [self.f.window, duplicate]
                self.assertIsNone(await self.f.read())
                self.assertIn('across profiles or incognito', self.f.chrome.reasons[self.f.access])
        self.assertFalse(any(m['method'] == 'Target.attachToTarget' for m in self.peer.calls))
        self.f.chrome.bounds = lambda hwnd: (10, 20, 800, 600) if hwnd == 1 else (500, 20, 800, 600)
        self.assertEqual((await self.f.read())['source'], 'cdp')

    async def test_background_title_cannot_map_a_native_window(self):
        self.peer.windows[0]['tabs'][0]['title'] = 'Different active tab'
        self.peer.windows[0]['tabs'][1]['title'] = 'Lab'
        self.assertIsNone(await self.f.read())
        self.assertFalse(any(m['method'] == 'Target.attachToTarget' for m in self.peer.calls))

    async def test_chrome_cancel_stays_on_uia_until_a_new_share_even_across_transport_change(self):
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        self.peer.feed({'method': 'Partyline.grantCancelled', 'params': {'grant': 'g'}})
        self.peer.feed({'method': 'Target.detachedFromTarget', 'params': {'sessionId': page.session}})
        await self.f.browser.call('Browser.getVersion')
        before = len(self.peer.calls)
        self.assertIsNone(await self.f.read())
        self.assertIn('cancelled', self.f.chrome.reasons[self.f.access])
        self.assertEqual(self.f.chrome.metadata(self.f.access), {})
        self.assertFalse(any(m['method'] in ('Target.attachToTarget', 'Partyline.scope')
                             for m in self.peer.calls[before:]))
        with self.assertRaises(CDPError):
            await self.f.browser.call('Target.attachToTarget', {'targetId': '1'})
        original = self.f.chrome.browser
        self.f.chrome.browser = BrowserConnection()
        self.assertIsNone(await self.f.chrome.page(self.f.access))
        self.assertIsNone(self.f.chrome.connecting)
        self.f.chrome.browser = original
        self.f.chrome.revoke(self.f.access)
        self.f.access.grant = self.f.window.copy()
        self.f.access.session.window_grant_id = 'new-share'
        self.f.shares.grants['new-share'] = self.f.shares.grants.pop('g')
        self.assertEqual((await self.f.read())['source'], 'cdp')

    async def test_status_distinguishes_disconnected_extension_and_remote_approval(self):
        self.f.chrome.report('refused', 'Connection ended')
        self.assertIn('extension disconnected', self.f.session.status.chrome)
        original = self.f.chrome.browser
        self.f.chrome.browser = BrowserConnection()
        self.f.chrome.report('awaiting_approval', 'Approve in Chrome')
        self.assertIn('remote debugging awaiting approval', self.f.session.status.chrome)
        self.assertNotIn('not installed', self.f.session.status.chrome)
        self.f.chrome.browser = original

    async def test_stale_endpoint_never_replaces_an_existing_remote_connection(self):
        import json
        import tempfile
        from pathlib import Path
        from partyline_helper import native_host
        remote = BrowserConnection()
        remote.socket, remote.state = self.f.socket, 'connected'
        self.f.chrome.browser, self.f.chrome.auto_transport = remote, True
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            endpoint = directory / 'native.json'
            endpoint.write_text(json.dumps({'port': 1234, 'token': 'a' * 64, 'pid': 12345}))
            with patch.object(native_host, 'endpoint_path', return_value=endpoint), \
                    patch('partyline_helper.instance.lock_dir', return_value=directory):
                for _ in range(2):
                    self.assertIs(await chrome_operations.select_extension(self.f.chrome), remote)
                self.assertIs(remote.socket, self.f.socket)
                self.assertFalse(remote.closed)

    async def test_extension_page_crash_recovery_owns_a_distinct_replacement_session(self):
        from unittest.mock import AsyncMock
        await self.f.read()
        page = await self.f.chrome.page(self.f.access)
        page.quiet.wait = AsyncMock(return_value='quiet')
        self.peer.feed({'method': 'Inspector.targetCrashed', 'sessionId': page.session, 'params': {}})
        await self.f.browser.call('Browser.getVersion')
        self.assertEqual(page.page_state, 'crashed')
        result = await self.f.chrome.action(self.f.access, {'action': 'reload', 'element_id': 'page'})
        self.assertEqual(result['status'], 'completed')
        fresh = self.f.chrome.pages[self.f.access][page.target]
        self.assertNotEqual(page.session, fresh.session)
        self.assertEqual(fresh.page_state, 'alive')
        self.assertTrue(fresh.live)
