"""Dedicated models stream to 64 MiB while regular and batch limits stay fixed."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from partyline.mcp import tools_core
from partyline.mcp.client import MAX_MODEL_UPLOAD, MAX_UPLOAD, PartylineClient
from partyline.mcp.uploads import MAX_TOTAL_UPLOAD
from tests.test_mcp import Connection, Response


class ModelLimitTests(unittest.TestCase):
    def test_model_boundary_streams_and_oversize_fails_before_connection(self):
        self.assertEqual(MAX_MODEL_UPLOAD, 64 * 1024 * 1024)
        self.assertEqual(MAX_UPLOAD, 20 * 1024 * 1024)
        self.assertEqual(MAX_TOTAL_UPLOAD, 60 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.glb'
            with path.open('wb') as stream:
                stream.truncate(MAX_MODEL_UPLOAD)
            conn = Connection(Response())
            sent = []
            conn.send = lambda chunk: sent.append(len(chunk))
            client = PartylineClient.__new__(PartylineClient)
            client.connection = {'conversation_id': 'home', 'token': 'test'}
            client._origin = Mock(return_value=conn)
            tools_core.call(client, 'upload_3d_model', {'path': str(path), 'client_key': 'key'},
                            {'actions': ['write']})
            self.assertEqual(sum(sent), int(conn.headers['Content-Length']))
            self.assertGreater(sum(sent), MAX_MODEL_UPLOAD)
            client._origin.reset_mock()
            with self.assertRaises(ValueError):
                client.upload('home', str(path), client_key='regular')
            with path.open('ab') as stream:
                stream.write(b'x')
            with self.assertRaises(ValueError):
                tools_core.call(client, 'upload_3d_model',
                                {'path': str(path), 'client_key': 'oversize'},
                                {'actions': ['write']})
            client._origin.assert_not_called()
