"""The kernel journal is privileged, bounded, and redacted before it leaves the host."""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.auth_guard import Principal
from partyline.kernel_log import redact, register_kernel_log_route
from partyline.mcp import tools_captain


def client():
    app = FastAPI()
    actors = {
        'person': Principal(kind='user', name='person'),
        'root': Principal(kind='machine', name='root', conv_id='root', is_lead=True),
        'child': Principal(kind='machine', name='child', conv_id='child', is_lead=True),
        'worker': Principal(kind='machine', name='worker', conv_id='root'),
    }

    @app.middleware('http')
    async def identity(request, call_next):
        request.state.principal = actors[request.headers.get('actor', 'person')]
        return await call_next(request)

    db = SimpleNamespace(get_conversation=lambda ident: {'parent_id': None if ident == 'root' else 'root'})
    register_kernel_log_route(app, SimpleNamespace(db=db))
    return TestClient(app)


class KernelLogTests(unittest.TestCase):
    def test_authorization_bounds_and_command(self):
        api = client()
        result = subprocess.CompletedProcess([], 0, 'token=abc\nnormal\n', '')
        with patch('partyline.kernel_log.subprocess.run', return_value=result) as run:
            for actor, code in [('person', 200), ('root', 200), ('child', 403), ('worker', 403)]:
                response = api.get('/api/host/kernel-log', headers={'actor': actor})
                assert response.status_code == code
                if code == 200:
                    assert response.json() == ['token=[REDACTED]', 'normal']
            assert run.call_count == 2
            assert run.call_args.args[0] == ['journalctl', '-k', '-b', '-1', '-n', '100',
                                             '--no-pager', '-o', 'short-iso']
            assert api.get('/api/host/kernel-log?boot=current&lines=300').status_code == 200
            assert run.call_args.args[0][3:6] == ['0', '-n', '300']
            for query in ('lines=301', 'lines=0', 'boot=other'):
                assert api.get('/api/host/kernel-log?' + query).status_code == 422


    def test_redaction(self):
        text = ('token=abc password="a b" secret=shh key=123 Bearer abc.def '
                'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature '
                'aa:bb:cc:dd:ee:ff 192.168.1.22 2001:db8::1234 ::1')
        output = redact(text)
        for value in ('abc', 'a b', 'shh', '123', 'eyJ', 'aa:bb', '192.168', '2001:db8', '::1'):
            assert value not in output
        for line in ('2026-10-01T12:34:56+00:00 host kernel: NVRM: Xid (PCI:0000:01:00): 79',
                     'pcieport 0000:00:01.0: AER: Corrected error received',
                     'NVRM: Xid (PCI:0000:41:00): 31, pid=1234, name=worker'):
            assert redact(line) == line


    def test_failures(self):
        api = client()
        for error, expected in [(FileNotFoundError(), 'install'), (PermissionError(), 'systemd-journal'),
                                (subprocess.TimeoutExpired('journalctl', 5), 'timed out'),
                                (OSError(), 'installation')]:
            with patch('partyline.kernel_log.subprocess.run', side_effect=error):
                response = api.get('/api/host/kernel-log')
                assert response.status_code == 503
                assert expected in response.json()['detail']
        failed = subprocess.CompletedProcess([], 1, '', 'denied')
        with patch('partyline.kernel_log.subprocess.run', return_value=failed):
            assert 'systemd-journal' in api.get('/api/host/kernel-log').json()['detail']
        denied = subprocess.CompletedProcess([], 0, '', 'insufficient permissions')
        with patch('partyline.kernel_log.subprocess.run', return_value=denied):
            assert api.get('/api/host/kernel-log').status_code == 503


    def test_captain_operation(self):
        root = {'kind': 'machine', 'role': 'lead', 'is_lead': True, 'parent_id': None, 'actions': []}
        child = {**root, 'parent_id': 'root'}
        assert 'kernel_log' in tools_captain.permitted(root)
        assert 'kernel_log' not in tools_captain.permitted(child)
        calls = []
        fake = SimpleNamespace(request=lambda *args: calls.append(args) or ['line'])
        assert tools_captain.call(fake, 'kernel_log', {'boot': 'current', 'lines': 5}, root) == ['line']
        assert calls == [('GET', '/api/host/kernel-log?boot=current&lines=5')]
