"""Installer shutdown is explicit; normal helper restarts retain the Chrome port."""
import unittest
from unittest.mock import AsyncMock, Mock, patch

from partyline_helper import cli, native_shutdown
from tests.test_native_host import Writer, reader


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_suspend_sends_authenticated_control_then_waits_for_eof(self):
        writer = Writer()
        opener = AsyncMock(return_value=(reader({'result': {}}), writer))
        await native_shutdown.suspend({'port': 1234, 'token': 'secret'}, opener)
        self.assertTrue(writer.closed)
        self.assertIn(b'Partyline.suspend', writer.output.getvalue())
        self.assertIn(b'secret', writer.output.getvalue())


class ShutdownCommandTests(unittest.TestCase):
    def test_idle_missing_host_and_successful_pause(self):
        host = Mock(return_value=None)
        self.assertIn('not running', native_shutdown.pause_for_install(host=host))
        host.return_value = 12
        with patch.object(native_shutdown, 'discover', return_value={'port': 1234}), \
                patch.object(native_shutdown, 'suspend', Mock(return_value='work')):
            runner, wait = Mock(), Mock(return_value=True)
            self.assertIn('paused', native_shutdown.pause_for_install(host, wait, runner))
            runner.assert_called_once_with('work')
            wait.assert_called_once_with(12, timeout=5)
            wait.return_value = False
            with self.assertRaises(RuntimeError):
                native_shutdown.pause_for_install(host, wait, runner)
            wait.side_effect = OSError('WinError: process unavailable')
            with self.assertRaisesRegex(RuntimeError, 'Disable Partyline Chrome'):
                native_shutdown.pause_for_install(host, wait, runner)
            wait.side_effect = None
            runner.side_effect = OSError('offline')
            with self.assertRaises(RuntimeError):
                native_shutdown.pause_for_install(host, wait, runner)
        with patch.object(native_shutdown, 'discover', return_value=None):
            self.assertIn('paused', native_shutdown.pause_for_install(host, Mock(return_value=True), Mock()))
        with patch.object(native_shutdown, 'pause_for_install', return_value='paused') as pause, \
                patch('builtins.print'):
            cli.main(['suspend-chrome'])
            pause.assert_called_once()
