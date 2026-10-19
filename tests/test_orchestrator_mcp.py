"""Task MCP tools expose role-scoped schemas and fixed server routes."""

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline.mcp import tools_tasks
from partyline.mcp.client import ApiError
from partyline.mcp.server import MCPServer


class TaskToolsTest(unittest.TestCase):
    def setUp(self):
        self.client = SimpleNamespace(home='root', request=Mock(return_value={'ok': True}),
                                      connection={'api': 'http://lan.example:8642'})
        self.root = {'kind': 'machine', 'role': 'lead', 'is_lead': True, 'conv_id': 'root',
                     'actions': ['create_task', 'tasks', 'review_verdict']}

    def test_scoped_tools_and_fixed_routes(self):
        self.assertEqual({t['name'] for t in tools_tasks.tool_list(self.root)},
                         {'create_task', 'tasks', 'review_verdict'})
        worker = {'actions': ['request_review']}
        reviewer = {'actions': ['review_verdict']}
        self.assertEqual([t['name'] for t in tools_tasks.tool_list(worker)], ['request_review'])
        self.assertEqual([t['name'] for t in tools_tasks.tool_list(reviewer)], ['review_verdict'])
        self.assertEqual(tools_tasks.tool_list({'actions': []}), [])
        tools_tasks.call(self.client, 'create_task', {
            'name': 'task', 'goal': 'goal', 'implementer': 'builder'}, self.root)
        self.client.request.assert_called_with('POST', '/api/conversations/root/tasks',
                                               {'name': 'task', 'goal': 'goal', 'implementer': 'builder'})
        tools_tasks.call(self.client, 'tasks', {}, self.root)
        self.client.request.assert_called_with('GET', '/api/conversations/root/tasks', None)
        tools_tasks.call(self.client, 'review_verdict', {
            'conv_id': 'task id', 'verdict': 'approve', 'findings': 'reviewed'}, self.root)
        self.client.request.assert_called_with('POST', '/api/conversations/task%20id/review-verdict',
                                               {'verdict': 'approve', 'findings': 'reviewed'})
        with self.assertRaises(ApiError):
            tools_tasks.call(self.client, 'create_task', {}, worker)
        for bad in ({}, {'verdict': 'magic', 'findings': 'bad', 'conv_id': 'task'},
                    {'verdict': 'approve', 'findings': 'ok', 'conv_id': 'task', 'path': '/api'}):
            with self.assertRaises(ValueError):
                tools_tasks.call(self.client, 'review_verdict', bad, self.root)

    def test_stdio_server_discovers_and_dispatches_task_tools_live(self):
        output = io.StringIO()
        self.client.capabilities = Mock(return_value=self.root)
        server = MCPServer(self.client, output)
        server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        listing = json.loads(output.getvalue().splitlines()[-1])
        self.assertIn('create_task', {t['name'] for t in listing['result']['tools']})
        server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                       'params': {'name': 'tasks', 'arguments': {}}})
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertNotIn('isError', result['result'])
        self.client.capabilities.return_value = {'actions': []}
        server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                       'params': {'name': 'tasks', 'arguments': {}}})
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertTrue(result['result']['isError'])
