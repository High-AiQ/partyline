"""Exercise the native entry point and real boot probe without opening a port."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'win32', 'native foreground startup')
class WindowsStartupIntegrationTest(unittest.TestCase):
    def test_entrypoint_runs_capped_server_and_native_preflight(self):
        script = '''
from unittest.mock import patch
from fastapi.testclient import TestClient
from partyline import launch, server, windows_server
class LocalServer:
    def __init__(self, config):
        self.config = config
    def run(self):
        assert windows_server._server_job is not None
        with TestClient(server.app) as client:
            registration = client.post('/api/auth/register', json={
                'email': 'fixture@example.test', 'password': 'fixture-password', 'handle': 'fixture'})
            assert registration.status_code == 201, registration.text
            token = registration.json()['access_token']
            response = client.get('/api/fence/status', headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == 200, response.text
            status = response.json()
            assert status['ok'], status
            assert status['backend'] == 'restricted-token', status
            assert client.get('/').status_code == 200
with patch.object(server.uvicorn, 'Server', LocalServer):
    launch.main([])
assert windows_server._server_job is None
server.runtime.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith('PARTYLINE_')}
            environment['PARTYLINE_DB'] = str(Path(directory, 'startup.db'))
            result = subprocess.run([sys.executable, '-c', script], env=environment,
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
