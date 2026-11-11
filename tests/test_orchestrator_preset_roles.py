"""Stored task roles are checked again before each staffing operation."""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline.orchestrator_contracts import ReopenIn, TaskIn
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_revive import restart_implementer, restart_reviewer
from partyline.orchestrator_service import create_task
from partyline.orchestrator_staff import ensure_reviewer
from partyline.preset_roles import require_resume
from tests.orchestrator_fixture import TaskFixture


class TaskPresetRolesTest(TaskFixture):
    def traits(self, name, implements, manage):
        self.db._exec('UPDATE presets SET implements=?,can_manage=? WHERE name=?',
                      (implements, manage, name))

    async def test_create_matrix_and_review_policy(self):
        for implements, manage in ((0, 0), (0, 1), (1, 0), (1, 1)):
            self.traits('builder', implements, manage)
            body = TaskIn(name=f'task-{implements}-{manage}', goal='work',
                          implementer='builder', review='none')
            if implements:
                result = await create_task(self.runtime, self.captain, 'root', body)
                self.assertEqual(result['implementer_preset'], 'builder')
            else:
                with self.assertRaises(HTTPException) as error:
                    await create_task(self.runtime, self.captain, 'root', body)
                self.assertIn('Fast implementer', error.exception.detail)
        self.traits('builder', 1, 0)
        for manage in (0, 1):
            self.traits('inspector', 1, manage)
            body = TaskIn(name=f'review-{manage}', goal='work', implementer='builder', review='inspector')
            if manage:
                result = await create_task(self.runtime, self.captain, 'root', body)
                self.assertEqual(result['policy'], 'inspector')
            else:
                with self.assertRaises(HTTPException) as error:
                    await create_task(self.runtime, self.captain, 'root', body)
                self.assertIn('Can manage a line', error.exception.detail)

    async def test_restart_and_reopen_refuse_changed_implementer_before_side_effects(self):
        row = await self.create('captain')
        self.db.set_attachment_status(row['implementer_id'], 'detached', None)
        self.traits('builder', 0, 1)
        with self.assertRaises(HTTPException):
            await restart_implementer(self.runtime, self.captain, self.conv_id)
        self.db._exec("UPDATE task_reviews SET status='done' WHERE conv_id=?", (self.conv_id,))
        with self.assertRaises(HTTPException):
            await reopen_task(self.runtime, self.captain, self.conv_id, ReopenIn(goal='new'))
        self.assertEqual(self.row()['status'], 'done')
        self.traits('builder', 1, 0)
        with patch('partyline.orchestrator_reopen.restart', new=AsyncMock()):
            self.assertEqual((await reopen_task(self.runtime, self.captain, self.conv_id,
                                               ReopenIn(goal='new')))['status'], 'implementing')

    async def test_reviewer_restaff_and_restart_refuse_changed_preset(self):
        await self.create()
        self.db._exec("UPDATE task_reviews SET status='in_review' WHERE conv_id=?", (self.conv_id,))
        self.traits('inspector', 1, 0)
        with self.assertRaises(HTTPException):
            await ensure_reviewer(self.runtime, self.row())
        with self.assertRaises(HTTPException):
            await restart_reviewer(self.runtime, self.captain, self.conv_id)
        self.assertIsNone(self.row()['reviewer_id'])
        self.traits('inspector', 0, 1)
        with patch('partyline.orchestrator_revive.revive_reviewer', new=AsyncMock()) as revive:
            await restart_reviewer(self.runtime, self.captain, self.conv_id)
            revive.assert_awaited_once()
        with patch('partyline.orchestrator_staff.spawn', new=AsyncMock()) as spawn:
            await ensure_reviewer(self.runtime, self.row())
            spawn.assert_awaited_once()

    async def test_restaff_uses_recorded_traits_after_command_edit(self):
        row = await self.create()
        owner = self.db.get_attachment(row['implementer_id'])['runtime_owner']
        self.db.set_attachment_status(row['implementer_id'], 'detached', owner)
        self.db._exec("UPDATE presets SET command='fake --new-flag' WHERE name='builder'")
        restarted = await restart_implementer(self.runtime, self.captain, self.conv_id)
        self.assertEqual(restarted['implementer_id'], row['implementer_id'])
        self.assertEqual(require_resume(self.db, row['implementer_id']), 'implementer')
        self.db._exec('UPDATE task_reviews SET review_worktree=? WHERE conv_id=?',
                      (self.repo, self.conv_id))
        reviewer = await ensure_reviewer(self.runtime, self.row())
        self.db.set_attachment_status(reviewer['id'], 'detached', reviewer['runtime_owner'])
        self.db._exec("UPDATE attachments SET cli_session='existing' WHERE id=?", (reviewer['id'],))
        self.db._exec("UPDATE presets SET command='fake --new-flag' WHERE name='inspector'")
        with patch('partyline.server._resume_adapter', new=AsyncMock(side_effect=self.resume)) as resume:
            await ensure_reviewer(self.runtime, self.row())
            resume.assert_awaited_once_with(reviewer['id'])
        self.assertEqual(require_resume(self.db, reviewer['id']), 'reviewer')

    async def test_person_can_resume_task_and_captain_when_agent_cannot(self):
        row = await self.create()
        self.traits('builder', 0, 0)
        for ident in (row['implementer_id'], 'captain'):
            self.assertIsNone(require_resume(self.db, ident, person=True))
            with self.assertRaises(HTTPException):
                require_resume(self.db, ident)
