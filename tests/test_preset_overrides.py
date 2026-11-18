"""Preset overrides change only validated model and effort arguments."""

import shlex
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from partyline.preset_overrides import attachment_command, label, rewrite


class PresetOverrideTests(unittest.TestCase):
    def test_rewrite_existing_and_missing_flags(self):
        for adapter, command, expected in (
            ('claude', "'my launcher' --model old --effort=high --other 'two words'",
             ['my launcher', '--model', 'new/model', '--effort=low', '--other', 'two words']),
            ('claude', 'wrapper --other yes',
             ['wrapper', '--other', 'yes', '--model', 'new/model', '--effort', 'low']),
            ('codex', "wrapper --model=old --config 'model_reasoning_effort=\"high\"' --config a=b",
             ['wrapper', '--model=new/model', '--config', 'model_reasoning_effort="low"',
              '--config', 'a=b']),
            ('codex', 'wrapper -m old', ['wrapper', '-m', 'new/model',
                                        '--config', 'model_reasoning_effort="low"']),
            ('claude', 'wrapper -- prompt',
             ['wrapper', '--model', 'new/model', '--effort', 'low', '--', 'prompt']),
            ('codex', 'wrapper --other yes',
             ['wrapper', '--other', 'yes', '--model', 'new/model', '--config',
              'model_reasoning_effort="low"']),
        ):
            with self.subTest(adapter=adapter, command=command):
                self.assertEqual(shlex.split(rewrite(adapter, command, 'new/model', 'low')), expected)

    def test_reject_injection_and_unsupported_adapter(self):
        for value in ('bad space', 'bad"quote', "bad'quote", 'bad;command', '$(command)', 'bad\nline'):
            for key in ('model', 'effort'):
                with self.subTest(value=value, key=key), self.assertRaises(HTTPException) as error:
                    rewrite('codex', 'wrapper', **{key: value})
                self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(HTTPException) as error:
            rewrite('raw', 'wrapper', effort='low')
        self.assertEqual(error.exception.status_code, 422)
        self.assertIn('claude and codex', error.exception.detail)

    def test_missing_flag_value_does_not_consume_another_option(self):
        for command, override in (('wrapper --model --other', {'model': 'new'}),
                                  ('wrapper --config --other', {'effort': 'low'})):
            with self.subTest(command=command), self.assertRaises(HTTPException):
                rewrite('codex', command, **override)

    def test_attachment_requires_matching_preset(self):
        db = SimpleNamespace(list_presets=lambda: [dict(name='one', adapter='codex', command='wrapper')])
        body = SimpleNamespace(model=None, effort='medium', preset_name='one',
                               adapter='codex', command='evil')
        with self.assertRaises(HTTPException):
            attachment_command(db, body)
        body.command = 'wrapper'
        result, selected = attachment_command(db, body)
        self.assertEqual(shlex.split(result)[0], 'wrapper')
        self.assertEqual(selected['name'], 'one')
        self.assertEqual(label('one', effort='medium'), 'one (effort medium)')


from unittest.mock import patch

from partyline import server
from partyline.adapters.base import Adapter
from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_revive import restart_implementer
from partyline.orchestrator_service import create_task
from tests.orchestrator_fixture import TaskFixture


class OverridePersistenceTests(TaskFixture):
    async def test_unsupported_task_returns_422(self):
        self.actor = self.captain
        result = self.client.post('/api/conversations/root/tasks', json={
            'name': 'unsupported', 'goal': 'work', 'implementer': 'builder',
            'review': 'none', 'effort': 'low'})
        self.assertEqual(result.status_code, 422)
        self.assertIn('claude and codex', result.json()['detail'])

    async def test_review_override_requires_a_reviewer_preset(self):
        self.actor = self.captain
        for policy in ('none', 'captain'):
            result = self.client.post('/api/conversations/root/tasks', json={
                'name': 'no reviewer', 'goal': 'work', 'implementer': 'builder',
                'review': policy, 'review_model': 'model', 'review_effort': 'low'})
            self.assertEqual(result.status_code, 422)
            self.assertIn('reviewer preset', result.json()['detail'])

    async def test_task_override_survives_restart_and_is_listed(self):
        self.db._exec("UPDATE presets SET adapter='codex',command='wrapper --model old' WHERE name='builder'")
        with patch.dict(server.ADAPTERS, {'codex': Adapter}), patch.dict(
                server.ADAPTER_METADATA, {'codex': {'command': ['wrapper']}}):
            body = TaskIn(name='override', goal='work', implementer='builder', review='none',
                          model='new', effort='medium')
            row = await create_task(self.runtime, self.captain, 'root', body)
            self.conv_id = row['conv_id']
            ident = row['implementer_id']
            before = self.db.get_attachment(ident)
            self.assertEqual(before['model_override'], 'new')
            self.assertEqual(before['effort_override'], 'medium')
            self.assertEqual(self.row()['effort'], 'medium')
            from partyline.staffing import staffing_line
            self.assertIn('builder (model new, effort medium)', staffing_line(self.db, 'root'))
            audit = [m for m in self.db.list_messages(self.conv_id) if 'Preset override by' in m['body']]
            self.assertEqual(len(audit), 1)
            self.assertIn('captain (captain): role implementer, preset builder, model new, effort medium',
                          audit[0]['body'])
            self.assertEqual(audit[0]['source_attachment_id'], 'captain')
            self.assertEqual(self.client.get('/api/conversations/root/tasks').json()[0]['model'], 'new')
            self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (ident,))
            self.runtime.live.pop(ident, None)
            await restart_implementer(self.runtime, self.captain, self.conv_id)
            after = self.db.get_attachment(ident)
            self.assertEqual(after['command'], before['command'])
            self.assertEqual(after['effort_override'], 'medium')

    async def test_reviewer_override_and_database_reopen(self):
        from partyline.db import Db
        from partyline.orchestrator_staff import ensure_reviewer

        self.db._exec("UPDATE presets SET adapter='claude',command='wrapper --effort high' "
                      "WHERE name='inspector'")
        with patch.dict(server.ADAPTERS, {'claude': Adapter}), patch.dict(
                server.ADAPTER_METADATA, {'claude': {'command': ['wrapper']}}):
            row = await create_task(self.runtime, self.captain, 'root', TaskIn(
                name='review override', goal='work', implementer='builder', review='inspector',
                review_effort='low'))
            self.conv_id = row['conv_id']
            self.assertTrue(any('role reviewer, preset inspector, model unchanged, effort low' in m['body']
                                for m in self.db.list_messages(self.conv_id)))
            self.db._exec('UPDATE task_reviews SET review_worktree=? WHERE conv_id=?',
                          (self.repo, self.conv_id))
            reviewer = await ensure_reviewer(self.runtime, self.row())
            self.assertEqual(reviewer['effort_override'], 'low')
            other = Db(self.directory.name + '/test.db')
            try:
                self.assertEqual(other.get_attachment(reviewer['id'])['effort_override'], 'low')
                self.assertEqual(other._exec('SELECT review_effort FROM task_reviews WHERE conv_id=?',
                                             (self.conv_id,)).fetchone()['review_effort'], 'low')
            finally:
                other.close()


class OverrideAttachTests(TaskFixture):
    def setUp(self):
        super().setUp()
        from partyline.conversation_routes import register_conversation_routes
        from partyline.media import MediaStore
        self.db.create_conversation('child', 'Child')
        self.db._exec("UPDATE conversations SET parent_id='root',cwd=? WHERE id='child'", (self.repo,))
        register_conversation_routes(self.app, self.runtime,
                                     MediaStore(self.db, self.directory.name + '/media'),
                                     None, {}, {}, self.start)
        self.actor = self.captain
        self.db.save_preset('codex', 'Codex', 'luna', 'codex', 'wrapper --model old')

    async def test_attach_validates_and_records_override(self):
        with patch.dict(server.ADAPTERS, {'codex': Adapter}), patch.dict(
                server.ADAPTER_METADATA, {'codex': {'command': ['wrapper']}}), patch(
                'partyline.conversation_routes.ensure_placed', return_value=None):
            path = '/api/conversations/child/attachments'
            base = {'name': 'worker', 'adapter': 'codex', 'preset_name': 'luna', 'effort': 'medium'}
            result = self.client.post(path, json=base)
            self.assertEqual(result.status_code, 200, result.text)
            att = self.db.get_attachment(result.json()['id'])
            self.assertEqual(att['preset'], 'luna')
            self.assertEqual(att['effort_override'], 'medium')
            messages = self.db.list_messages('child')
            audit = next(m for m in messages if 'Preset override by' in m['body'])
            self.assertIn('captain (captain): role implementer, preset luna, model unchanged, effort medium',
                          audit['body'])
            self.assertEqual(audit['source_attachment_id'], 'captain')
            for data in ({**base, 'preset_name': None}, {**base, 'command': 'evil'},
                         {**base, 'adapter': 'fake', 'preset_name': 'builder'}):
                data['name'] = 'other'
                self.assertEqual(self.client.post(path, json=data).status_code, 422)
