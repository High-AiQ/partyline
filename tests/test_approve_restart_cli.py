"""The local operator CLI sends a one-use grant only to loopback."""

import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

from scripts import approve_restart as cli


class OperatorCliTest(unittest.TestCase):
    def test_approval_uses_one_request_and_no_proxy_or_redirect(self):
        response = Mock()
        response.read.return_value = b'{"request": null}'
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(cli, 'issue', return_value='token') as issue, \
                patch.object(cli.urllib.request, 'build_opener', return_value=opener), \
                patch('builtins.print'):
            self.assertEqual(cli.main(['--database', '/db', '--request', 'a' * 12]), 0)
        issue.assert_called_once_with('/db', 'a' * 12)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8643/api/restart-request/operator-approve')
        self.assertEqual(json.loads(request.data), {'request_id': 'a' * 12, 'token': 'token'})
        with self.assertRaisesRegex(OSError, 'redirect'):
            cli.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')

    def test_missing_schema_or_bad_port_is_an_actionable_failure(self):
        with patch.object(cli, 'issue', side_effect=sqlite3.OperationalError('missing schema')), \
                self.assertRaises(SystemExit) as exit_code:
            cli.main(['--database', '/db', '--request', 'a' * 12])
        self.assertEqual(exit_code.exception.code, 1)
        with self.assertRaises(SystemExit) as exit_code:
            cli.main(['--database', '/db', '--request', 'a' * 12, '--port', '0'])
        self.assertEqual(exit_code.exception.code, 2)
