"""Task-line mentions that would reach nobody: a former captain, and a gone reviewer."""

import unittest
from unittest.mock import AsyncMock, patch

from partyline.mcp.captain_schemas import validate
from partyline.mcp.validation import validate_arguments
from partyline.orchestrator_contracts import ReviewRequestIn
from partyline.orchestrator_service import request_review
from tests.orchestrator_fixture import TaskFixture


class MentionFallbackTest(TaskFixture):
    async def setUp_task(self):
        await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)

    async def say(self, body, sender=None, conv_id=None):
        message = self.db.add_message(conv_id or self.conv_id, sender or self.worker.name, 'agent', body)
        await self.runtime.route_mentions(conv_id or self.conv_id, message)

    def bodies(self, conv_id, **match):
        return [m['body'] for m in self.db.message_page(conv_id, limit=100)[0]
                if all(m.get(k) == v for k, v in match.items())]

    async def in_review(self):
        await self.setUp_task()
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what='feature', where='code'))
        return self.db.get_attachment(self.row()['reviewer_id'])

    async def test_former_root_captain_is_relayed_to_the_current_one(self):
        await self.setUp_task()
        self.db.add_attachment('astra', 'root', 'astra', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='astra'")
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)
        await self.say('done @astra')
        copies = [m for m in self.db.messages_after('root', 0)
                  if m.get('audience_attachment_id') == 'captain']
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]['body'],
                         '↪ @astra is no longer attached on the root line; '
                         'delivered to the current captain @captain:\ndone @astra')
        self.assertEqual(copies[0]['source_conv_id'], self.conv_id)
        hints = self.bodies(self.conv_id, audience_attachment_id=self.worker.attachment_id)
        self.assertIn('⚠ @astra is not attached; the root captain is @captain', hints)
        self.assertFalse([b for b in self.bodies(self.conv_id) if 'nothing was delivered' in b])

    async def test_mentioning_the_current_captain_too_is_not_relayed_twice(self):
        await self.setUp_task()
        self.db.add_attachment('astra', 'root', 'astra', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='astra'")
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)
        await self.say('done @astra @Captain')
        self.assertFalse([m for m in self.db.messages_after('root', 0) if m['body'].startswith('↪')])
        self.assertIn('⚠ @astra is not attached; the root captain is @captain',
                      self.bodies(self.conv_id, audience_attachment_id=self.worker.attachment_id))

    async def test_former_captain_with_no_live_current_captain_is_not_relayed(self):
        await self.setUp_task()
        self.db.add_attachment('astra', 'root', 'astra', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='astra'")
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='captain'")
        await self.say('done @astra')
        self.assertFalse([m for m in self.db.messages_after('root', 0)
                          if m.get('audience_attachment_id')])

    async def test_a_human_mention_of_a_former_captain_is_not_relayed(self):
        await self.setUp_task()
        self.db.add_attachment('astra', 'root', 'astra', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='astra'")
        message = self.db.add_message(self.conv_id, 'greg', 'human', 'hi @astra')
        await self.runtime.route_mentions(self.conv_id, message)
        self.assertFalse([m for m in self.db.messages_after('root', 0)
                          if m.get('audience_attachment_id')])

    async def test_detached_implementer_gets_the_revive_notice_and_no_revive(self):
        await self.setUp_task()
        impl = self.worker.name
        implementer = self.db.get_attachment(self.row()['implementer_id'])
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?", (implementer['id'],))
        with patch('partyline.orchestrator_revive.revive_reviewer', new=AsyncMock()) as revive:
            await self.say(f'ping @{impl}', sender='captain')
        revive.assert_not_awaited()
        notices = self.bodies(self.conv_id, sender_type='system')
        self.assertIn(f'⚠ @{impl} is detached; it will read this when revived — '
                      'the root captain revives it with restart_implementer', notices)
        self.assertFalse([n for n in notices if 'nothing was delivered' in n])

    async def test_detached_reviewer_while_implementing_gets_the_notice_only(self):
        reviewer = await self.in_review()
        self.db._exec("UPDATE task_reviews SET status='implementing' WHERE conv_id=?", (self.conv_id,))
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?", (reviewer['id'],))
        with patch('partyline.orchestrator_revive.revive_reviewer', new=AsyncMock()) as revive:
            await self.say(f"verdict please @{reviewer['name']}")
        revive.assert_not_awaited()
        self.assertIn(f"⚠ @{reviewer['name']} is detached; it will read this when revived — "
                      'the root captain revives it with restart_reviewer',
                      self.bodies(self.conv_id, sender_type='system'))

    async def test_in_review_with_a_detached_reviewer_is_revived(self):
        reviewer = await self.in_review()
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?", (reviewer['id'],))
        self.runtime.live.pop(reviewer['id'], None)
        await self.say(f"verdict? @{reviewer['name']}")
        self.assertEqual(self.db.get_attachment(reviewer['id'])['status'], 'running')
        notices = self.bodies(self.conv_id, sender_type='system')
        self.assertIn(f"⚠ @{reviewer['name']} is detached; it is being revived for this review "
                      'round and will read this', notices)
        self.assertFalse([n for n in notices if 'nothing was delivered' in n])

    async def test_failed_revive_falls_back_to_the_notice(self):
        reviewer = await self.in_review()
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (reviewer['id'],))
        self.runtime.live.pop(reviewer['id'], None)
        with patch('partyline.orchestrator_revive.revive_reviewer',
                   new=AsyncMock(side_effect=ValueError('boom'))):
            await self.say(f"verdict? @{reviewer['name']}")
        self.assertIn(f"⚠ @{reviewer['name']} is exited; it will read this when revived — "
                      'the root captain revives it with restart_reviewer',
                      self.bodies(self.conv_id, sender_type='system'))

    async def test_reviewer_at_the_restart_cap_gets_the_notice_only(self):
        reviewer = await self.in_review()
        self.db._exec("UPDATE task_reviews SET reviewer_restarts=2 WHERE conv_id=?", (self.conv_id,))
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?", (reviewer['id'],))
        self.runtime.live.pop(reviewer['id'], None)
        with patch('partyline.orchestrator_revive.revive_reviewer', new=AsyncMock()) as revive:
            await self.say(f"verdict? @{reviewer['name']}")
        revive.assert_not_awaited()
        self.assertEqual(self.row()['reviewer_restarts'], 2)
        self.assertIn(f"⚠ @{reviewer['name']} is detached; it will read this when revived — "
                      'the root captain revives it with restart_reviewer',
                      self.bodies(self.conv_id, sender_type='system'))

    async def test_in_review_reviewer_already_live_is_left_alone(self):
        reviewer = await self.in_review()
        from partyline.mention_fallbacks import _revive_in_review
        with patch('partyline.orchestrator_revive.revive_reviewer', new=AsyncMock()) as revive:
            self.assertFalse(await _revive_in_review(self.runtime, self.conv_id))
        revive.assert_not_awaited()
        self.assertEqual(self.db.get_attachment(reviewer['id'])['status'], 'running')


class EnumErrorTest(unittest.TestCase):
    def test_captain_enum_error_lists_values(self):
        with self.assertRaisesRegex(ValueError, r"operation must be one of list, get, post; "
                                    r"acknowledging a report is the captain op "
                                    r"ack_report\(conv_id, report_id, revision\)"):
            validate('reports', {'operation': 'ack'})


    def test_core_enum_error_lists_values_and_hint(self):
        schema = {'properties': {'operation': {'type': 'string', 'enum': ['list', 'get', 'post']}}}
        with self.assertRaisesRegex(ValueError, r'operation must be one of list, get, post; see ack_report'):
            validate_arguments(schema, {'operation': 'acknowledge'}, 'see ack_report')
        with self.assertRaisesRegex(ValueError, r'operation must be one of list, get, post$'):
            validate_arguments(schema, {'operation': 'x'})
