"""An agent whose @mention reached nobody is told privately, once, in a way that wakes it."""

from unittest.mock import AsyncMock, patch

from partyline.unreached import explain
from tests.orchestrator_fixture import TaskFixture
from tests.test_return_path import Recorder, Tree

MARK = "did not reach everyone"


class AgentSpeakerTest(Tree):
    def setUp(self):
        super().setUp()
        self.db.add_attachment("gone", "parent", "gone", "fake", ["fake"], self.tmp.name, "x")
        self.db.set_attachment_status("gone", "detached", "x")

    def told(self, att_id):
        return [m for batch in self.adapters[att_id].delivered for m in batch if MARK in m["body"]]

    def public(self, conv_id):
        return [m for m in self.line(conv_id)
                if m["sender_type"] == "system" and not m.get("audience_attachment_id")]

    async def test_every_unreached_handle_is_listed_once_with_its_reason(self):
        await self.say("worker", "@gone @builder please look")

        [notice] = self.told("worker")
        self.assertEqual(notice["audience_attachment_id"], "worker")
        self.assertEqual(notice["sender_type"], "system")
        self.assertIn("gone: detached; ask @lead, its captain, to resume it", notice["body"])
        self.assertIn("builder is on line «Child», not this one", notice["body"])
        self.assertIn("tell @lead, your captain, instead", notice["body"])
        self.assertEqual(self.public("parent"), [])  # nothing for the line to read instead
        self.assertEqual(len(self.adapters["worker"].delivered), 1)  # one wake, no more

    async def test_a_gone_sub_captain_points_at_the_captain_above_it(self):
        self.db.set_attachment_status("sub", "detached", "own")

        self.assertEqual(
            explain(self.db, "child", "sub", "builder"),
            "detached — a captain. The reachable captain is @lead; mention that handle instead")

    async def test_an_unknown_handle_wakes_any_agent_not_only_a_task_worker(self):
        for who in ("lead", "worker"):
            await self.say(who, "@nobody-here please take this")

            [notice] = self.told(who)
            self.assertIn("@nobody-here: unknown handle", notice["body"])

    async def test_a_stray_word_in_a_handed_off_message_wakes_nobody(self):
        """A captain's report said "an AI whose @mention reaches nobody" and was woken over it,
        apologised in public quoting the word, and was woken again."""
        self.db._exec("INSERT INTO users(email, handle, password_hash, created_at)"
                      " VALUES('g@x', 'greg', 'h', 1)")
        for who, body in (("lead", "Fixed: an AI whose @mention reaches nobody is told.\n\n@greg"),
                          ("lead", "@worker use @dataclass and @pytest.fixture here"),
                          ("worker", "@lead done; @property was the fix")):
            await self.say(who, body)

            self.assertEqual(self.told(who), [], body)

    async def test_a_handle_quoted_as_code_is_not_a_failed_hand_off(self):
        await self.say("lead", "Skip names like `@nobody-here`.\n```\n@app.get('/x')\n```")

        self.assertEqual(self.told("lead"), [])
        self.assertEqual(self.public("parent"), [])

    async def test_a_slip_of_a_real_handle_is_still_told_even_when_someone_was_reached(self):
        await self.say("lead", "@workr build it; @sub review it after")

        [notice] = self.told("lead")
        self.assertIn("@workr: unknown handle — did you mean @worker?", notice["body"])
        self.assertNotIn("@sub", notice["body"])

    async def test_a_transposed_handle_counts_as_a_slip(self):
        await self.say("lead", "@wroker build it; @sub review it after")

        [notice] = self.told("lead")
        self.assertIn("@wroker: unknown handle — did you mean @worker?", notice["body"])

    async def test_a_real_handle_gone_from_another_line_is_never_a_stray_word(self):
        """Review of the first cut: reaching @sub hid that @builder, detached below, got nothing."""
        self.db.set_attachment_status("builder", "detached", "own")
        self.runtime.live.pop("builder")

        await self.say("lead", "@sub review it; @builder build it")

        [notice] = self.told("lead")
        self.assertIn("@builder: no live process you can reach wears that handle now", notice["body"])

    async def test_a_handle_from_an_unrelated_tree_is_not_offered_as_the_fix(self):
        self.db.create_conversation("elsewhere", "Elsewhere")
        self.db.add_attachment("stranger", "elsewhere", "stranger", "fake", ["fake"], self.tmp.name, "x")
        self.db.set_attachment_status("stranger", "running", "x")

        await self.say("lead", "@worker take this, not @strangr")

        self.assertEqual(self.told("lead"), [])

    async def test_one_message_crossing_two_lines_wakes_its_speaker_once(self):
        for att_id in ("sub", "builder"):
            self.db.set_attachment_status(att_id, "starting", "own")
            self.runtime.live.pop(att_id)

        await self.say("lead", "@sub @builder please take this")

        [notice] = self.told("lead")
        for name in ("sub", "builder"):
            self.assertIn(f"{name}: has no live process behind it", notice["body"])
        self.assertEqual(len(self.adapters["lead"].delivered), 1)

    async def test_a_message_that_reached_everyone_gets_no_notice(self):
        await self.say("lead", "@worker take this")

        self.assertEqual(self.told("lead"), [])
        self.assertEqual(self.adapters["lead"].delivered, [])
        self.assertEqual(self.public("parent"), [])

    async def test_a_person_keeps_the_notice_on_the_line(self):
        await self.human("parent", "@gone are you there")

        self.assertEqual([m["body"] for m in self.public("parent")],
                         ["⚠ @gone was mentioned but is not attached — nothing was delivered"])
        for att_id in ("lead", "worker"):
            self.assertEqual(self.told(att_id), [])

    async def test_the_notice_is_not_a_request_and_starts_no_loop(self):
        await self.say("worker", "@gone hello")
        [notice] = self.told("worker")
        before = len(self.line("parent"))

        await self.runtime.route_mentions("parent", notice, force=True)  # processed again

        self.assertEqual(len(self.line("parent")), before)
        self.assertEqual(len(self.told("worker")), 1)
        self.assertEqual(self.runtime.returns.requesters.get("worker", {}), {})
        self.assertEqual(self.returns_to("worker"), [])

    async def test_answering_the_notice_by_naming_the_same_handle_is_not_told_again(self):
        """Woken by the notice alone, a speaker's reply about that handle woke it again."""
        await self.say("worker", "@gone hello")
        self.assertEqual(len(self.told("worker")), 1)

        await self.say("worker", "@gone is detached, so I will ask for it to be resumed")
        self.assertEqual(len(self.told("worker")), 1)  # the notice already said so

        await self.say("worker", "@gone @builder then")  # a handle the notice did not carry
        self.assertEqual(len(self.told("worker")), 2)
        self.assertIn("builder is on line", self.told("worker")[1]["body"])

    async def test_a_reply_that_is_not_the_turns_first_message_is_still_an_answer(self):
        """A plain sentence, or a word to someone else, before the reply must not reset the memory.

        Found in review of #496: forgetting whatever a message did not repeat brought the
        loop back for every turn of two messages, which is an ordinary turn.
        """
        await self.say("worker", "@gone hello")
        for turn in range(3):
            await self.say("worker", "Let me look into why that did not go through.")
            await self.say("worker", "@lead I am checking on gone")
            await self.say("worker", "@gone is detached, so I will ask for it to be resumed")
            self.assertEqual(len(self.told("worker")), 1, turn)

    async def test_a_handle_reached_in_between_is_reported_when_it_is_gone_again(self):
        """The memory must not outlive a hand-off that worked: found in review of #496."""
        await self.say("worker", "@gone hello")
        self.assertEqual(len(self.told("worker")), 1)

        self.db.set_attachment_status("gone", "running", "x")
        revived = Recorder("x")
        revived.att.update(id="gone", name="gone")
        self.runtime.live["gone"] = self.presence.watch(
            revived, "parent", "gone", "receipt", *self.runtime.held_wake_hooks("parent", "gone", "gone"))
        await self.say("worker", "@gone are you back")  # this one is delivered
        self.assertEqual(len(revived.delivered), 1)
        self.assertNotIn("worker", self.runtime.returns.told)
        self.db.set_attachment_status("gone", "detached", "x")
        self.runtime.live.pop("gone")

        await self.say("worker", "@gone the branch is ready, please merge it")
        self.assertEqual(len(self.told("worker")), 2)

    async def test_a_handle_reached_by_relay_on_another_line_is_reported_when_gone_again(self):
        """A captain naming a process on the line below is the ordinary hand-off (review of #496)."""
        builder = self.runtime.live.pop("builder")
        self.db.set_attachment_status("builder", "detached", "own")
        await self.say("lead", "@builder build it")
        self.assertEqual(len(self.told("lead")), 1)

        self.db.set_attachment_status("builder", "running", "own")
        self.runtime.live["builder"] = builder
        await self.say("lead", "@builder are you back")
        self.assertEqual(len(self.adapters["builder"].delivered), 1)  # the relay reached it
        self.assertNotIn("lead", self.runtime.returns.told)

        self.runtime.live.pop("builder")
        self.db.set_attachment_status("builder", "detached", "own")
        await self.say("lead", "@builder the branch is ready, please merge it")
        self.assertEqual(len(self.told("lead")), 2)

    async def test_a_new_wake_makes_the_same_slip_news_again(self):
        await self.say("worker", "@gone hello")
        await self.human("parent", "@worker try gone once more")  # real work arrives

        await self.say("worker", "@gone hello again")

        self.assertEqual(len(self.told("worker")), 2)
        self.runtime.returns.forget("worker")
        self.assertNotIn("worker", self.runtime.returns.told)

    async def test_a_bridge_message_keeps_its_behaviour(self):
        message = self.db.add_message("parent", "worker", "agent", "@gone hello")
        message = {**message, "bridge_id": "b1"}
        with patch("partyline.message_routing.route_bridge", new=AsyncMock(return_value=False)):
            await self.runtime.route_mentions("parent", message)

        self.assertEqual(self.told("worker"), [])
        self.assertEqual(self.public("parent"), [])

    async def test_the_wake_reaches_a_speaker_whose_turn_has_already_ended(self):
        message = self.db.add_message("parent", "worker", "agent", "@gone hello")
        self.runtime.returns.note_spoke("worker", message["body"])

        await self.runtime.route_mentions("parent", message)  # after its turn: only the server speaks

        self.assertEqual(len(self.told("worker")), 1)


class TaskWorkerTest(TaskFixture):
    async def setUp_task(self):
        await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        self.runtime.live["captain"].deliver = AsyncMock(return_value=True)

    async def say(self, conv_id, body, speaker):
        message = self.db.add_message(conv_id, speaker.name, "agent", body)
        self.db._exec("UPDATE messages SET source_attachment_id=? WHERE id=?",
                      (speaker.attachment_id, message["id"]))
        message = self.db.message_by_id(conv_id, message["id"])
        await self.runtime.route_mentions(conv_id, message)

    def told(self, speaker, conv_id):
        return [m["body"] for m in self.db.list_messages(conv_id)
                if m.get("audience_attachment_id") == speaker.attachment_id and MARK in m["body"]]

    async def test_a_captain_naming_a_detached_task_worker_learns_the_remedy(self):
        await self.setUp_task()
        impl = self.row()["implementer_handle"]
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?",
                      (self.row()["implementer_id"],))

        await self.say("root", f"@{impl} please fix it", self.captain)

        [notice] = self.told(self.captain, "root")
        self.assertIn(f"{impl}: detached — a task implementer", notice)
        self.assertIn(f"restart_implementer(conv_id={self.conv_id})", notice)
        self.assertIn(f"message_task(conv_id={self.conv_id}", notice)
        self.assertEqual([m for m in self.db.list_messages("root")
                          if "nothing was delivered" in m["body"]], [])

    async def test_a_root_captain_hears_of_an_unknown_handle(self):
        await self.setUp_task()

        await self.say("root", "@nobody-here please take this", self.captain)

        [notice] = self.told(self.captain, "root")
        self.assertIn("@nobody-here: unknown handle", notice)

    async def test_a_captain_naming_detached_staff_on_the_task_line_is_woken_once(self):
        await self.setUp_task()
        impl = self.row()["implementer_handle"]
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?",
                      (self.row()["implementer_id"],))
        self.runtime.live["captain"].deliver.reset_mock()

        await self.say(self.conv_id, f"@{impl} please take this assignment", self.captain)

        self.assertEqual(self.runtime.live["captain"].deliver.await_count, 1)
        [notice] = self.told(self.captain, "root")
        self.assertIn(f"restart_implementer(conv_id={self.conv_id})", notice)
        recorded = self.db._exec("SELECT COUNT(*) FROM task_ghost_mentions").fetchone()[0]
        self.assertEqual(recorded, 1)  # the incident is still on record

    async def test_held_back_and_withheld_task_workers_carry_their_own_conv_id(self):
        first = await self.create()
        second = await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        self.runtime.live["captain"].deliver = AsyncMock(return_value=True)
        impl = second["implementer_handle"]

        await self.say(first["conv_id"], f"@{impl} please fix", self.captain)
        [notice] = self.told(self.captain, "root")

        self.assertIn(f"conv_id {second['conv_id']}", notice)
        self.assertIn(f"message_task(conv_id={second['conv_id']}, text, to='implementer')", notice)

    async def test_a_gone_captain_with_no_other_captain_says_so(self):
        await self.setUp_task()
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='captain'")
        self.db.add_attachment("astra", "root", "astra", "fake", ["fake"], self.repo, "owner")
        self.db._exec("UPDATE attachments SET status='detached', is_lead=1 WHERE id='astra'")

        self.assertEqual(
            explain(self.db, "root", "astra", "captain"),
            "detached — a captain, and no captain is reachable right now; tell a person")

    async def test_a_task_workers_stray_word_is_quiet_and_its_slip_still_wakes_it(self):
        await self.setUp_task()
        before = len(self.db.list_messages(self.conv_id))

        await self.say(self.conv_id, "@captain done; @property was the fix", self.worker)

        self.assertEqual(self.told(self.worker, self.conv_id), [])
        self.assertFalse([m for m in self.db.list_messages(self.conv_id)[before + 1:]
                          if "property" in m["body"]])

        await self.say(self.conv_id, "@captain done; @captian please look", self.worker)

        [notice] = self.told(self.worker, self.conv_id)
        self.assertIn("@captian: unknown handle — did you mean @captain?", notice)

    async def test_one_notice_carries_a_former_captain_and_an_unknown_handle(self):
        await self.setUp_task()
        self.db.add_attachment("astra", "root", "astra", "fake", ["fake"], self.repo, "owner")
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='astra'")

        await self.say(self.conv_id, "@astra and @nobody-here", self.worker)

        [notice] = self.told(self.worker, self.conv_id)
        self.assertIn("astra: not attached; the root captain is @captain", notice)
        self.assertIn("@nobody-here: unknown handle — line names are not mentionable", notice)
