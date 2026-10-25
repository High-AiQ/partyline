"""Ghost task-handle and line-name mentions are refused before they land.

Covers the sender's private correction, the one-time private incident notice
to the root captain (which task, who mentioned whom, reviewer state, recovery
ops), and the mention of this task's own detached staff that still lands but
is reported once.
"""

from unittest.mock import AsyncMock

from fastapi import HTTPException

from partyline.auth_store import create_user
from partyline.message_routing import post_identified
from partyline.orchestrator_contracts import ReviewRequestIn
from partyline.orchestrator_pack import task_pack
from partyline.orchestrator_service import request_review
from tests.orchestrator_fixture import TaskFixture


class GhostMentionTest(TaskFixture):
    async def say(self, body):
        return await post_identified(self.runtime, self.conv_id, self.worker, body)

    async def refused(self, body):
        with self.assertRaises(HTTPException) as caught:
            await self.say(body)
        return caught.exception

    def agent_bodies(self):
        return [r["body"] for r in self.db._exec(
            "SELECT body FROM messages WHERE conv_id=? AND sender_type='agent'",
            (self.conv_id,)).fetchall()]

    def notices(self):
        return [m["body"] for m in self.db.messages_after("root", 0)
                if m.get("audience_attachment_id") == "captain"
                and "ghost mention" in m["body"]]

    def bind_routing(self):
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        self.runtime.live["captain"].deliver = AsyncMock(return_value=True)

    async def test_a_missing_reviewer_handle_is_refused_before_it_is_posted(self):
        await self.create(policy="captain")
        tag = self.row()["tag"]
        error = await self.refused(f"done @review-{tag}")
        self.assertEqual(error.status_code, 422)
        self.assertIn(f"@review-{tag} reached nobody", error.detail)
        self.assertIn("mention @captain", error.detail)
        self.assertNotIn(f"done @review-{tag}", self.agent_bodies())
        notices = self.notices()
        self.assertEqual(len(notices), 1)
        for piece in ("«slice»", f"@{self.worker.name} mentioned @review-{tag}",
                      "no reviewer is staffed", "restart_reviewer", "restart_implementer",
                      "message_task the implementer to ask again"):
            self.assertIn(piece, notices[0])
        self.assertEqual(len(self.db._exec("SELECT 1 FROM task_ghost_mentions").fetchall()), 1)

    async def test_repeating_the_same_ghost_mention_is_quiet(self):
        await self.create(policy="captain")
        tag = self.row()["tag"]
        await self.refused(f"done @review-{tag}")
        await self.refused(f"done @review-{tag}")
        self.assertEqual(len(self.notices()), 1)
        self.assertEqual(len(self.db._exec("SELECT 1 FROM task_ghost_mentions").fetchall()), 1)

    async def test_a_line_name_is_refused_too(self):
        await self.create(policy="captain")
        error = await self.refused("@slice status?")
        self.assertEqual(error.status_code, 422)
        self.assertIn("@slice reached nobody", error.detail)
        self.assertIn("mention @captain", error.detail)

    async def test_live_handles_and_people_are_not_ghosts(self):
        await self.create(policy="captain")
        create_user(self.db, "g@example.com", "greg", "x")
        stored = await self.say("@captain and @greg: status?")
        self.assertEqual(stored["body"], "@captain and @greg: status?")
        self.assertEqual(self.notices(), [])

    async def test_detached_own_staff_still_lands_but_is_reported_once(self):
        await self.create(policy="inspector")
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what="feature", where="code"))
        reviewer = self.db.get_attachment(self.row()["reviewer_id"])
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (reviewer["id"],))
        # Back to implementing so the mention does not auto-revive the reviewer.
        self.db._exec("UPDATE task_reviews SET status='implementing' WHERE conv_id=?",
                      (self.conv_id,))
        self.bind_routing()
        stored = await self.say(f"@{reviewer['name']} please look again")
        self.assertEqual(stored["body"], f"@{reviewer['name']} please look again")
        notices = self.notices()
        self.assertEqual(len(notices), 1)
        self.assertIn("the reviewer is exited", notices[0])
        await self.say(f"@{reviewer['name']} again")
        self.assertEqual(len(self.notices()), 1)

    async def test_speech_off_a_task_line_is_not_guarded(self):
        await self.create(policy="captain")
        stored = await post_identified(self.runtime, "root", self.captain, "@review-deadbe ping")
        self.assertEqual(stored["body"], "@review-deadbe ping")
        self.assertEqual(self.notices(), [])

    async def test_spoken_ghost_mention_reaches_the_captain_once_too(self):
        await self.create(policy="captain")
        tag = self.row()["tag"]
        self.bind_routing()
        for _ in range(2):
            message = self.db.add_message(self.conv_id, self.worker.name, "agent",
                                          f"done @review-{tag}")
            await self.runtime.route_mentions(self.conv_id, message)
        notices = self.notices()
        self.assertEqual(len(notices), 1)
        self.assertIn(f"@{self.worker.name} mentioned @review-{tag}", notices[0])
        self.assertIn("no reviewer is staffed", notices[0])
        hints = [m["body"] for m in self.db.message_page(self.conv_id, limit=100)[0]
                 if "reached nobody" in m["body"]]
        self.assertEqual(len(hints), 2)  # the sender's hint still fires every time

    async def test_pack_tells_the_implementer_the_reviewer_is_server_staffed(self):
        await self.create(policy="captain")
        pack = task_pack(self.db, self.conv_id, "implementer")
        self.assertIn("request_review is the hand-off", pack)
        self.assertIn("the server staffs the reviewer and notifies it", pack)
        self.assertIn("never @mention review-<tag>/impl-<tag> handles", pack)
        self.assertIn("your task, or its line name", pack)


if __name__ == "__main__":
    import unittest

    unittest.main()
