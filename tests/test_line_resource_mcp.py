"""Resource leases are discoverable and callable through real stdio dispatch."""

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline.mcp.server import MCPServer


class ResourceMCPTest(unittest.TestCase):
    def test_live_role_discovery_dispatch_and_revocation(self):
        output = io.StringIO()
        state = {'kind': 'machine', 'role': 'implementer', 'is_lead': False, 'actions': ['read']}
        client = SimpleNamespace(home='task', request=Mock(return_value={'status': 'held'}),
                                 capabilities=Mock(return_value=state),
                                 connection={'api': 'http://lan.example:8642'})
        server = MCPServer(client, output)
        server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        listing = json.loads(output.getvalue().splitlines()[-1])
        names = {tool['name'] for tool in listing['result']['tools']}
        self.assertTrue({'acquire_resource', 'release_resource'}.issubset(names))
        call = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                'params': {'name': 'acquire_resource', 'arguments': {'name': 'gpu'}}}
        server.handle(call)
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertNotIn('isError', result['result'])
        client.request.assert_called_with('POST', '/api/task/resources/gpu/acquire', {'note': ''})
        client.capabilities.return_value = {'kind': 'machine', 'role': 'worker', 'actions': ['read']}
        server.handle(call)
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertTrue(result['result']['isError'])
        self.assertEqual(client.request.call_count, 1)
