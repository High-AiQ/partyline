"""Task uploads reach only home and root, through both MCP and media routes."""

from pathlib import Path
from unittest.mock import Mock

from fastapi import HTTPException

from partyline.auth_guard import Principal
from partyline.machine_scope import allows, capability_state, deny_unless
from partyline.media import MediaStore
from partyline.media_routes import media_router
from partyline.mcp import tools_core
from partyline.mcp.client import ApiError
from tests.orchestrator_fixture import TaskFixture


class TaskUploadTests(TaskFixture):
    async def test_task_upload_destinations_and_other_operations(self):
        await self.create()
        self.db.create_conversation('sibling', 'Sibling')
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='sibling'")
        self.db.create_conversation('unrelated', 'Unrelated')
        self.app.include_router(media_router(
            self.runtime, MediaStore(self.db, Path(self.directory.name) / 'media')))
        self.actor = self.worker
        path = Path(self.directory.name) / 'scene.gltf'
        path.write_text('{"asset":{"version":"2.0"}}')
        client = Mock()
        client.home = self.conv_id
        client.capabilities.side_effect = lambda target: capability_state(self.db, self.worker, target)
        state = capability_state(self.db, self.worker)
        for target in (self.conv_id, 'root', 'sibling', 'unrelated'):
            allowed = target in (self.conv_id, 'root')
            self.assertEqual(allows(self.db, self.worker, target, 'upload'), allowed)
            for name, args in (
                ('upload_file', {'path': str(path)}),
                ('upload_3d_model', {'path': str(path)}),
                ('upload_files', {'paths': [str(path)]}),
            ):
                with self.subTest(target=target, tool=name):
                    args = {**args, 'conv_id': target, 'client_key': 'key'}
                    if allowed:
                        tools_core.call(client, name, args, state)
                        method = client.upload_files if name == 'upload_files' else client.upload
                        self.assertEqual(method.call_args.args[0], target)
                    else:
                        with self.assertRaisesRegex(ApiError, 'not authorized'):
                            tools_core.call(client, name, args, state)
            for route in ('files', 'images'):
                response = self.client.post(
                    f'/api/conversations/{target}/{route}',
                    files={'file': ('scene.gltf', path.read_bytes(), 'model/gltf+json')})
                self.assertEqual(response.status_code, 200 if allowed else 403, response.text)
        for capability in ('write', 'assign', 'attach', 'close', 'read'):
            self.assertFalse(allows(self.db, self.worker, 'root', capability))
        for name, args in (('upload_file', {'path': str(path)}),
                           ('upload_files', {'paths': [str(path)]})):
            with self.assertRaisesRegex(ValueError, 'omit body'):
                tools_core.call(client, name, {**args, 'body': 'caption', 'client_key': 'key'}, state)
            with self.assertRaisesRegex(ApiError, 'upload-only access to this line cannot carry a caption'):
                tools_core.call(client, name, {**args, 'conv_id': 'root', 'body': 'caption',
                                             'client_key': 'key'}, state)
            tools_core.call(client, name, {**args, 'conv_id': 'root', 'body': '  ',
                                         'client_key': 'key'}, state)
        for route in ('files', 'images'):
            for target, body, expected in (('root', 'caption @captain', 403),
                                            ('root', '  ', 200),
                                            (self.conv_id, 'own caption', 200)):
                before = self.db._exec('SELECT COUNT(*) FROM messages').fetchone()[0]
                self.runtime.route_mentions.reset_mock()
                response = self.client.post(
                    f'/api/conversations/{target}/{route}', data={'body': body},
                    files={'file': ('scene.gltf', path.read_bytes(), 'model/gltf+json')})
                self.assertEqual(response.status_code, expected, response.text)
                if expected == 403:
                    self.assertEqual(response.json()['detail'],
                                     'upload-only access to this line cannot carry a caption')
                    self.assertEqual(self.db._exec('SELECT COUNT(*) FROM messages').fetchone()[0],
                                     before)
                    self.runtime.route_mentions.assert_not_called()
                else:
                    if target == self.conv_id:
                        self.assertEqual(response.json()['message']['body'].splitlines()[0],
                                         'own caption')
                    else:
                        self.assertTrue(response.json()['message']['body'].startswith('🧊 scene.gltf'))

        # Ordinary child workers do not inherit a task's upload exception.
        ordinary = Principal(kind='machine', name='ordinary', conv_id='sibling')
        self.assertFalse(allows(self.db, ordinary, 'root', 'upload'))
        unknown = Principal(kind='unknown', name='unknown')
        self.assertFalse(allows(self.db, unknown, 'root', 'upload'))
        self.db.retiring_lines = {'root'}
        with self.assertRaises(HTTPException) as refused:
            deny_unless(self.db, self.worker, 'root', 'upload')
        self.assertEqual(refused.exception.status_code, 409)
        self.db.retiring_lines.clear()
        self.db._exec("UPDATE conversations SET archived_at='now' WHERE id='root'")
        response = self.client.post('/api/conversations/root/files',
                                    files={'file': ('x.txt', b'x', 'text/plain')})
        self.assertEqual(response.status_code, 409)
