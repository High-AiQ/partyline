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
        self.client.request.assert_called_with('GET', '/api/conversations/root/tasks')
        tools_tasks.call(self.client, 'tasks', {'include_retired': True}, self.root)
        self.client.request.assert_called_with(
            'GET', '/api/conversations/root/tasks?retired_only=true&limit=11&offset=0')
        with self.assertRaises(ValueError):
            tools_tasks.call(self.client, 'tasks', {'include_retired': 'yes'}, self.root)
        full = {'conv_id': 'task id', 'findings': 'finding ' * 400}
        self.client.request.return_value = full
        self.assertEqual(tools_tasks.call(self.client, 'tasks', {'conv_id': 'task id'}, self.root), full)
        self.client.request.assert_called_with('GET', '/api/conversations/task%20id/task')
        self.client.request.return_value = {'ok': True}
        tools_tasks.call(self.client, 'review_verdict', {
            'conv_id': 'task id', 'verdict': 'approve', 'findings': 'reviewed'}, self.root)
        self.client.request.assert_called_with('POST', '/api/conversations/task%20id/review-verdict',
                                               {'verdict': 'approve', 'findings': 'reviewed'})
        tools_tasks.call(self.client, 'review_verdict', {
            'conv_id': 'task id', 'verdict': 'changes', 'findings': 'rework', 'override': True},
            self.root)
        self.client.request.assert_called_with('POST', '/api/conversations/task%20id/review-verdict',
                                               {'verdict': 'changes', 'findings': 'rework',
                                                'override': True})
        schema = {t['name']: t['inputSchema'] for t in tools_tasks.tool_list(reviewer)}
        self.assertEqual(schema['review_verdict']['properties']['override']['type'], 'boolean')
        with self.assertRaises(ApiError):
            tools_tasks.call(self.client, 'create_task', {}, worker)
        for bad in ({}, {'verdict': 'magic', 'findings': 'bad', 'conv_id': 'task'},
                    {'verdict': 'approve', 'findings': 'ok', 'conv_id': 'task', 'path': '/api'},
                    {'verdict': 'approve', 'findings': 'ok', 'conv_id': 'task',
                     'override': 'yes'}):
            with self.assertRaises(ValueError):
                tools_tasks.call(self.client, 'review_verdict', bad, self.root)

    def test_the_board_fits_the_reply_whatever_the_tasks_wrote(self):
        from partyline.mcp.render import MAX_TEXT, render

        prose = 'finding ' * 400
        self.client.request.return_value = [
            {'conv_id': f'line-{index}', 'tag': f'tag{index}', 'status': 'in_review', 'merged': 0,
             'round': 2, 'sha': None, 'reviewer_id': '', 'goal': prose, 'findings': prose,
             'previous_findings': prose, 'what': prose, 'workspaces': []}
            for index in range(12)]
        board = tools_tasks.call(self.client, 'tasks', {}, self.root)
        self.assertEqual([row['tag'] for row in board], [f'tag{index}' for index in range(12)])
        first = board[0]
        self.assertEqual((first['status'], first['merged'], first['round']), ('in_review', 0, 2))
        self.assertFalse({'sha', 'reviewer_id', 'workspaces'} & set(first))  # unset: not listed
        self.assertEqual(len(first['findings']), tools_tasks.BOARD_TEXT + 1)
        self.assertTrue(first['findings'].endswith('…'))
        text = render(board, 'http://lan.example:8642')
        self.assertLess(len(text), MAX_TEXT)
        self.assertEqual(len(json.loads(text)), 12)  # whole, not cut mid-record
        self.client.request.return_value = {'detail': 'unexpected'}
        self.assertEqual(tools_tasks.call(self.client, 'tasks', {}, self.root), [])

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

    def test_set_task_goal_schema_and_route(self):
        state = {**self.root, 'actions': ['set_task_goal']}
        tool = tools_tasks.tool_list(state)[0]
        self.assertEqual(set(tool['inputSchema']['required']), {'conv_id', 'goal'})
        tools_tasks.call(self.client, 'set_task_goal', {'conv_id': 'child', 'goal': 'new'}, state)
        self.client.request.assert_called_with('POST', '/api/conversations/child/task/goal', {'goal': 'new'})
        with self.assertRaises(ValueError):
            tools_tasks.call(self.client, 'set_task_goal', {'goal': 'new'}, state)
