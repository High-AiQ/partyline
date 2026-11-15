"""CDP reads point to only safe, currently owned native dialog HWNDs."""
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from partyline.screen_tree import Snapshot
from partyline.screen_tree_answer import answer
from partyline_helper.cdp_dialogs import dialog_pointer
from partyline_helper.cdp_transport import CDPError
from partyline_helper.uia_window_list import discover_windows
from partyline_helper.window_standing_attach import attach
from tests.cdp_fakes import Fixture


class Dialogs(TestCase):
    def test_pointer_filters_floor_ownership_and_window_class(self):
        rows = [dict(hwnd=i, process=process, title=title) for i, process, title in (
            (1, 'chrome.exe', 'Page'), (2, 'chrome.exe', 'Open'),
            (3, 'chrome.exe', 'Other window'), (4, 'chrome.exe', 'Other popup'),
            (5, 'cmd.exe', 'Terminal'), (6, 'bitwarden.exe', 'Private'),
            (7, 'consent.exe', 'Security'))]
        scope = SimpleNamespace(pid=12, accepts=lambda hwnd: hwnd != 3,
                                class_name=lambda hwnd: '#32770' if hwnd != 4 else 'Chrome_WidgetWin_1')
        grant = {'hwnd': 1, 'pid': 12}
        pointer = dialog_pointer(grant, 'win32', lambda: rows, lambda hwnd: scope)
        self.assertIn('Open (window="2")', pointer)
        self.assertIn('screen_attach_window', pointer)
        self.assertIn('screen_attach_window(window="<hwnd>")', pointer)
        self.assertLess(pointer.index('screen_windows'), pointer.index('screen_attach_window'))
        self.assertIn("screen_elements(query='File name')", pointer)
        for forbidden in ('Terminal', 'Private', 'Security', 'Other window', 'Other popup'):
            self.assertNotIn(forbidden, pointer)
        self.assertIsNone(dialog_pointer({'hwnd': 1}, 'linux', Mock(side_effect=AssertionError)))
        self.assertIsNone(dialog_pointer({'hwnd': 1}, 'win32', lambda: None,
                                         Mock(side_effect=AssertionError)))
        self.assertIsNone(dialog_pointer(grant, 'win32', lambda: [], lambda hwnd: scope))
        self.assertIsNone(dialog_pointer({**grant, 'pid': 99}, 'win32', lambda: rows,
                                         lambda hwnd: scope))
        many = [dict(hwnd=i, process='chrome.exe', title='x' * 1000) for i in range(10, 30)]
        pointer = dialog_pointer(grant, 'win32', lambda: many, lambda hwnd: scope)
        self.assertEqual(pointer.count(' (window='), 4)
        self.assertNotIn('x' * 121, pointer)
        for row in many:
            row['title'] = '😀' * 1000
        pointer = dialog_pointer(grant, 'win32', lambda: many, lambda hwnd: scope)
        tree = Snapshot('s', 0)
        tree.source, tree.source_reason = 'cdp', pointer
        self.assertLess(len(json.dumps(answer(tree, {}, {'query': 'File name'}),
                                       ensure_ascii=False).encode()), 4096)


class Routing(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)

    async def test_cdp_query_exposes_native_pointer_and_plain_reads_clear_it(self):
        pointer = 'Open (window="22"): screen_windows then screen_attach_window then screen_elements'
        self.f.chrome.dialogs = Mock(return_value=pointer)
        result = await self.f.read(query_scope={'query': 'File name'})
        self.assertEqual(result['source'], 'cdp')
        self.assertEqual(result['source_reason'], pointer)
        self.f.chrome.dialogs.assert_called_once_with(self.f.access.grant)
        tree = Snapshot('s', 0)
        tree.source, tree.source_reason = result['source'], result['source_reason']
        self.assertEqual(answer(tree, {}, {'query': 'File name'})['source_reason'], pointer)
        self.f.chrome.dialogs.return_value = None
        self.assertNotIn('source_reason', await self.f.read())

    async def test_pointer_flow_lists_current_windows_before_attaching_the_dialog(self):
        row = dict(hwnd=22, pid=12, process='chrome.exe', title='Open', id='22')
        scope = SimpleNamespace(pid=12, accepts=lambda hwnd: hwnd == 22,
                                class_name=lambda hwnd: '#32770')
        self.f.chrome.dialogs = lambda grant: dialog_pointer(
            grant, 'win32', lambda: [row], lambda hwnd: scope)
        pointer = (await self.f.read())['source_reason']
        self.assertIn('window="22"', pointer)
        self.assertLess(pointer.index('screen_windows'), pointer.index('screen_attach_window'))
        self.f.session.window_access_enabled = True
        self.f.session.window_access_audit = SimpleNamespace(append=Mock())
        self.f.shares.request = AsyncMock(side_effect=[
            {'request_id': 'targets', 'lines': [{'line_id': 'line', 'standing_access': True}]},
            {'ok': True, 'target': {'line_id': 'line', 'line_name': 'Line'}}])
        self.f.shares.outline_factory = Mock(return_value=SimpleNamespace(start=AsyncMock(), close=Mock()))
        self.f.shares.start_events = AsyncMock()
        message = dict(request_id='attach', window='22', line='line', line_id='line', agent='agent')
        await attach(self.f.shares, message)
        self.assertEqual(self.f.session.send.await_args.kwargs['error'], 'window unavailable or protected')
        self.f.shares.request.assert_not_awaited()
        with patch('partyline_helper.uia_window_list.standing_windows', return_value=[row]), \
             patch('partyline_helper.uia_window_identity.mark', return_value='window-lifetime'):
            listed = await discover_windows(self.f.session)
        self.assertEqual(listed[0]['id'], '22')
        self.assertEqual(self.f.session.standing_window_rows['22']['marker'], 'window-lifetime')
        with patch('partyline_helper.uia_access.WindowAccess.check', AsyncMock(return_value=None)):
            await attach(self.f.shares, message)
        reply = self.f.session.send.await_args.kwargs
        self.assertTrue(reply['ok'])
        self.assertEqual(self.f.shares.grants[reply['window']]['access'].grant['hwnd'], 22)
        self.assertNotIn('22', self.f.session.standing_window_rows)

    async def test_revoke_during_native_discovery_discloses_no_result(self):
        def revoke(grant):
            self.f.access.gate.invalidate()
            return 'Open dialog'
        self.f.chrome.dialogs = revoke
        with self.assertRaisesRegex(CDPError, 'revoked'):
            await self.f.read()
