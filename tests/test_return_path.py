"""Cross-line mentions and the return path.

Two stalls from the book lines, each reproduced and closed here: a sub-manager
answering ``@lead`` on its own line while lead sat on the parent, and a
worker whose turn ended without handing off to anyone. Both used to leave the
tree idle with every process correct and nobody woken.
"""

import tempfile
import unittest

from partyline.adapters.briefing import format_digest
from partyline.db import Db
from partyline.hierarchy import create_child_conversation, set_lead
from partyline.mention_relay import post_private
from partyline.presence import Presence
from partyline.runtime import ChatRuntime
from partyline.turn_return import excerpt


class Recorder:
    """A live adapter that only records what the server pastes into it."""

    def __init__(self, owner: str):
        self.att = {"runtime_owner": owner}
        self.delivered: list[list[dict]] = []

    async def deliver(self, messages):
        self.delivered.append(messages)

    def bodies(self):
        return [m["body"] for batch in self.delivered for m in batch]


class Tree(unittest.IsolatedAsyncioTestCase):
    """Line «Parent» (manager lead, implementer worker) over line «Child»
    (manager sub, implementer builder)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.presence = Presence(self.runtime)
        self.db.create_conversation("parent", "Parent")
        create_child_conversation(self.db, "parent", "child", "Child")
        self.speakers = {}
        self.adapters = {}
        for att_id, line in (("lead", "parent"), ("worker", "parent"),
                             ("sub", "child"), ("builder", "child")):
            self.attach(att_id, line)
        set_lead(self.db, "parent", "lead")
        set_lead(self.db, "child", "sub")

    def attach(self, att_id, line):
        self.db.add_attachment(att_id, line, att_id, "fake", ["fake"], self.tmp.name, "own")
        self.db.set_attachment_status(att_id, "running", "own")
        adapter = Recorder("own")
        adapter.att["id"] = att_id
        adapter.att["name"] = att_id
        self.runtime.live[att_id] = self.presence.watch(
            adapter, line, att_id, "receipt", *self.runtime.held_wake_hooks(line, att_id, att_id)
        )
        self.adapters[att_id] = adapter
        self.speakers[att_id] = self.presence.posting(
            line, att_id, self.runtime.post_callback(att_id, line, "own")
        )

    async def say(self, att_id, body):
        """The process speaks through its pty: posted under its name, then routed."""
        await self.speakers[att_id](att_id, "agent", body)

    async def human(self, line, body, who="person"):
        return await self.runtime.post_message(line, who, "human", body)

    def line(self, conv_id):
        return self.db.message_page(conv_id, limit=100)[0]

    def unseen(self, att_id):
        att = self.db.get_attachment(att_id)
        return self.db.messages_after(att["conv_id"], 0, att["name"], att["id"])

    def notices(self, conv_id):
        return [m["body"] for m in self.line(conv_id) if m["sender_type"] == "system"]


class CrossLineMentionTest(Tree):
    async def test_a_child_manager_reporting_up_reaches_the_parent_manager(self):
        await self.say("sub", "@lead page one is done")

        self.assertEqual(self.adapters["lead"].bodies(), ["@lead page one is done"])
        copy = self.adapters["lead"].delivered[0][0]
        self.assertEqual(copy["conv_id"], "parent")
        self.assertEqual(copy["source_conv_id"], "child")
        self.assertEqual(copy["source_conv_name"], "Child")
        self.assertEqual(copy["source_attachment_id"], "sub")
        self.assertEqual(copy["audience_attachment_id"], "lead")
        self.assertEqual(self.notices("child"), [])

    async def test_a_relay_copy_is_private_to_its_addressee_but_visible_to_people(self):
        await self.say("sub", "@lead page one is done")

        self.assertEqual([m["body"] for m in self.unseen("worker")], [])
        self.assertEqual([m["body"] for m in self.line("parent")], ["@lead page one is done"])
        self.assertEqual(self.adapters["worker"].delivered, [])

    async def test_a_relay_copy_never_relays_again(self):
        """The copy names both handles; the one back on the child must not bounce."""
        await self.say("sub", "@lead @builder is blocked on assets")

        self.assertEqual(len(self.line("child")), 1)  # the original only
        self.assertEqual(len(self.line("parent")), 1)  # one copy, for lead
        self.assertEqual(self.adapters["builder"].bodies(), ["@lead @builder is blocked on assets"])

    async def test_a_manager_delegating_down_reaches_a_sub_line_process(self):
        await self.say("lead", "@builder render page one")

        self.assertEqual(self.adapters["builder"].bodies(), ["@builder render page one"])
        self.assertEqual(self.adapters["builder"].delivered[0][0]["audience_attachment_id"], "builder")
        self.assertEqual([m["body"] for m in self.unseen("sub")], [])
        self.assertEqual(self.adapters["sub"].delivered, [])

    async def test_an_implementer_cannot_reach_up_and_is_told_whom_to_tell(self):
        await self.say("builder", "@lead done")

        self.assertEqual(self.adapters["lead"].delivered, [])
        self.assertEqual(self.line("parent"), [])
        [notice] = self.notices("child")
        self.assertIn("lead is on line «Parent», not this one", notice)
        self.assertIn("tell @sub, your captain, instead", notice)
        self.assertEqual(self.adapters["sub"].delivered, [])  # an instruction, not a wake

    async def test_an_implementer_cannot_reach_down_either(self):
        await self.say("worker", "@builder can you check the assets")

        self.assertEqual(self.adapters["builder"].delivered, [])
        [notice] = self.notices("parent")
        self.assertIn("builder is on line «Child»", notice)
        self.assertIn("tell @lead, your captain", notice)

    async def test_a_manager_reaches_managers_above_but_not_their_implementers(self):
        await self.say("sub", "@worker please review")

        self.assertEqual(self.adapters["worker"].delivered, [])
        [notice] = self.notices("child")
        self.assertIn("only the captains above it", notice)

    async def test_a_person_may_cross_in_both_directions(self):
        await self.human("parent", "@builder how is page one?")
        await self.human("child", "@lead all good up there?")

        self.assertEqual(self.adapters["builder"].bodies(), ["@builder how is page one?"])
        self.assertEqual(self.adapters["lead"].bodies()[-1], "@lead all good up there?")
        self.assertEqual(self.adapters["builder"].delivered[0][0]["sender_type"], "human")

    async def test_all_rings_one_line_only(self):
        await self.say("lead", "@all status please")

        self.assertEqual(self.adapters["worker"].bodies(), ["@all status please"])
        self.assertEqual(self.adapters["builder"].delivered, [])
        self.assertEqual(self.adapters["sub"].delivered, [])

    async def test_a_handle_on_no_line_is_still_reported_missing(self):
        self.db.add_attachment("gone", "parent", "gone", "fake", ["fake"], self.tmp.name, "x")
        self.db.set_attachment_status("gone", "exited", "x")
        await self.say("lead", "@gone anyone there")

        self.assertIn("⚠ @gone was mentioned but is not attached — nothing was delivered",
                      self.notices("parent"))

    async def test_the_digest_tags_a_message_said_on_another_line(self):
        await self.say("sub", "@lead page one is done")
        digest = format_digest(self.adapters["lead"].delivered[0])

        self.assertTrue(digest.startswith("[sub via «Child»]: @lead page one is done"))

    async def test_the_digest_leaves_a_local_message_untagged(self):
        await self.say("worker", "@lead local note")

        self.assertTrue(
            format_digest(self.adapters["lead"].delivered[0]).startswith("[worker]: @lead local")
        )


class ReturnPathTest(Tree):
    def setUp(self):
        super().setUp()
        self.runtime.returns.grace = 0

    async def turn(self, att_id, *said, after=()):
        """A harness turn: began, speech, the receipt, then any speech the
        transcript tail posts after the receipt, then the grace runs out."""
        line = self.db.get_attachment(att_id)["conv_id"]
        await self.presence.began(line, att_id)
        for body in said:
            await self.say(att_id, body)
        await self.presence.ended(line, att_id)
        for body in after:
            await self.say(att_id, body)
        await self.runtime.returns.drain()

    async def test_speech_that_lands_after_the_receipt_is_what_gets_quoted(self):
        await self.say("lead", "@builder count the functions")
        await self.turn("builder", "On it.", after=("Two functions: add and mul.",))

        [notice] = [b for b in self.adapters["lead"].bodies() if b.startswith("↩")]
        self.assertIn("last said: «Two functions: add and mul.»", notice)

    async def test_a_hand_off_that_lands_after_the_receipt_cancels_the_notice(self):
        await self.say("lead", "@sub take page one")
        await self.turn("sub", "Checking.", after=("@lead page one accepted",))

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])
        self.assertEqual(self.runtime.returns.pending, {})

    async def test_a_cross_line_notice_points_at_everything_since_the_wake(self):
        wake = (await self.runtime.post_message("parent", "lead", "agent", "x"))["id"]
        await self.say("lead", "@builder count the functions")
        await self.turn("builder", "Two.")

        [notice] = [b for b in self.adapters["lead"].bodies() if b.startswith("↩")]
        self.assertIn(f"GET /api/conversations/child/messages?after_id={wake + 1}", notice)

    async def test_a_notice_to_a_child_captain_never_points_at_the_parent_line(self):
        """The child cannot read the parent line; a pointer it will only get
        403 from is worse than none."""
        await self.say("sub", "@lead page one is ready for review")
        await self.turn("lead", "Looking now.")

        [notice] = [b for b in self.adapters["sub"].bodies() if b.startswith("↩")]
        self.assertIn("lead on line «", notice)
        self.assertNotIn("Read it all", notice)

    async def test_a_same_line_notice_needs_no_pointer(self):
        await self.say("lead", "@worker run the suite")
        await self.turn("worker", "Green.")

        [notice] = [b for b in self.adapters["lead"].bodies() if b.startswith("↩")]
        self.assertNotIn("GET /api", notice)

    async def test_a_worker_that_ends_without_handing_off_wakes_the_manager_who_asked(self):
        await self.say("lead", "@builder render page one")
        await self.turn("builder", "Working now.", "Page one rendered at /tmp/p1.png, tests green.")

        [notice] = [b for b in self.adapters["lead"].bodies() if b.startswith("↩")]
        self.assertIn("@lead — builder on line «Child» ended its turn without handing off", notice)
        self.assertIn("last said: «Page one rendered at /tmp/p1.png, tests green.»", notice)
        row = self.adapters["lead"].delivered[-1][0]
        self.assertEqual(row["sender_type"], "system")
        self.assertEqual(row["audience_attachment_id"], "lead")
        self.assertEqual(row["source_conv_id"], "child")
        self.assertEqual([m for m in self.unseen("worker") if m["sender_type"] == "system"], [])

    async def test_a_return_notice_never_earns_a_return_of_its_own(self):
        await self.say("lead", "@builder render page one")
        await self.turn("builder", "Done, done.")
        parent_before = len(self.line("parent"))

        await self.turn("lead", "Noted; waiting on Greg.")

        self.assertEqual(len(self.line("parent")), parent_before + 1)  # lead's own words
        self.assertEqual(len(self.adapters["builder"].delivered), 1)  # never rung again

    async def test_handing_off_to_any_live_process_settles_the_turn(self):
        await self.say("lead", "@sub take page one")
        await self.turn("sub", "@builder build page one, no upload")

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])

    async def test_a_report_up_through_the_relay_settles_the_turn(self):
        await self.say("lead", "@sub take page one")
        await self.turn("sub", "@lead page one accepted")

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])
        self.assertEqual(self.adapters["lead"].bodies(), ["@lead page one accepted"])

    async def test_a_hand_off_that_could_not_cross_does_not_settle(self):
        """`@lead` from an implementer reaches nobody, so the manager who rang it hears."""
        await self.say("sub", "@builder render page one")
        await self.turn("builder", "@lead page one rendered")

        self.assertEqual(len([b for b in self.adapters["sub"].bodies() if b.startswith("↩")]), 1)

    async def test_undeliverable_closing_mention_wakes_line_captain_once(self):
        """A closing mention that reaches no live process rings the line captain once,
        even if the captain never asked, and leaves the warning notice unforced on the line."""
        await self.turn("builder", "@lead page one rendered")

        # Warning notice is posted on child line:
        notices = self.notices("child")
        self.assertTrue(any("only a line's captain talks to other lines" in n for n in notices))
        # Captain is woken ONCE with the return notice:
        self.assertEqual(len(self.adapters["sub"].delivered), 1)
        [notice] = [b for b in self.adapters["sub"].bodies() if b.startswith("↩")]
        self.assertIn("@sub — builder ended its turn without handing off to any process", notice)
        self.assertIn("last said: «＠lead page one rendered»", notice)

    async def test_unattached_closing_mention_wakes_line_captain_once(self):
        """A closing mention of an unattached handle rings the line captain once."""
        await self.turn("builder", "@nobody page one rendered")

        self.assertEqual(len(self.adapters["sub"].delivered), 1)
        [notice] = [b for b in self.adapters["sub"].bodies() if b.startswith("↩")]
        self.assertIn("@sub — builder ended its turn without handing off to any process", notice)

    async def test_deliverable_closing_mention_does_not_fire_return_notice(self):
        """When the closing mention reaches a process, normal hand-off occurs without a return notice."""
        await self.turn("builder", "@sub page one rendered")

        # Captain was woken by the message itself, not a return notice:
        self.assertEqual(self.adapters["sub"].bodies(), ["@sub page one rendered"])
        self.assertEqual([b for b in self.adapters["sub"].bodies() if b.startswith("↩")], [])

    async def test_mid_turn_deliverable_with_undeliverable_closing_wakes_captain(self):
        """A deliverable mention mid-turn does not prevent an undeliverable closing mention
        from ringing the line captain with the return notice."""
        await self.turn("builder", "@sub started rendering", "@nobody finished rendering")

        # First message woke sub directly, closing message woke sub via return notice:
        bodies = self.adapters["sub"].bodies()
        self.assertIn("@sub started rendering", bodies)
        return_notices = [b for b in bodies if b.startswith("↩")]
        self.assertEqual(len(return_notices), 1)
        self.assertIn("last said: «＠nobody finished rendering»", return_notices[0])

    async def test_mid_turn_undeliverable_with_deliverable_closing_settles_normally(self):
        """An undeliverable mention mid-turn does not cause a return notice if the closing mention
        reaches a live process."""
        await self.turn("builder", "@nobody started rendering", "@sub finished rendering")

        bodies = self.adapters["sub"].bodies()
        self.assertIn("@sub finished rendering", bodies)
        self.assertEqual([b for b in bodies if b.startswith("↩")], [])

    async def test_same_line_delegation_returns_to_the_requester(self):
        await self.say("lead", "@worker run the suite")
        await self.turn("worker", "Suite green, 120 tests.")

        [notice] = [b for b in self.adapters["lead"].bodies() if b.startswith("↩")]
        self.assertIn("@lead — worker ended its turn", notice)
        self.assertNotIn("on line", notice)

    async def test_a_manager_wrapping_up_to_a_person_does_not_bounce_to_its_implementer(self):
        await self.say("worker", "@lead suite is green")
        await self.turn("lead", "@person PR #12 is ready to merge")

        self.assertEqual([b for b in self.adapters["worker"].bodies() if b.startswith("↩")], [])

    async def test_an_implementer_asked_by_an_implementer_returns_to_it(self):
        await self.say("worker", "@lead suite is green")  # worker is not a manager
        set_lead(self.db, "parent", None)
        self.db.set_attachment_status("lead", "running", "own")
        await self.turn("lead", "Thanks.")

        [notice] = [b for b in self.adapters["worker"].bodies() if b.startswith("↩")]
        self.assertIn("@worker — lead ended its turn", notice)

    async def test_a_turn_woken_only_by_a_person_on_this_line_returns_nothing(self):
        await self.human("parent", "@worker run the suite")
        await self.turn("worker", "Suite green.")

        self.assertEqual(self.notices("parent"), [])

    async def test_a_person_asking_from_another_line_is_told_on_that_line(self):
        await self.human("parent", "@builder how is page one?")
        await self.turn("builder", "Built and waiting for approval.")

        [notice] = self.notices("parent")
        self.assertIn("@person — builder on line «Child» ended its turn", notice)
        self.assertEqual(self.adapters["lead"].delivered, [])  # unrouted: nobody is rung

    async def test_a_silent_turn_owes_nothing(self):
        await self.say("lead", "@builder render page one")
        await self.turn("builder")

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])

    async def test_words_said_before_the_wake_are_not_this_turns_answer(self):
        await self.say("builder", "Hello, builder is connected.")
        await self.say("lead", "@builder render page one")
        await self.turn("builder")

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])

    async def test_a_passing_mention_does_not_make_a_requester(self):
        """`@sub have builder build it` rings builder too, but only sub owes lead."""
        await self.say("lead", "@sub please have @builder build page one")
        await self.turn("builder", "Noted, waiting for sub.")

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])
        await self.turn("sub", "Reviewing the plan.")
        self.assertEqual(
            len([b for b in self.adapters["lead"].bodies() if b.startswith("↩")]), 1
        )

    async def test_a_status_line_naming_a_worker_owes_nothing_either(self):
        await self.say("lead", "@worker run the suite")
        await self.turn("worker", "Green.")
        lead_notices = len([b for b in self.adapters["lead"].bodies() if b.startswith("↩")])
        await self.say("lead", "@person suite is green; @worker is idle now.")
        await self.turn("worker", "Yes, idle.")

        self.assertEqual(
            len([b for b in self.adapters["lead"].bodies() if b.startswith("↩")]), lead_notices
        )

    async def test_an_exit_is_not_a_return(self):
        await self.say("lead", "@builder render page one")
        await self.presence.began("child", "builder")
        await self.say("builder", "Working.")
        await self.presence.statusing("child", "builder", self.runtime.status_callback(
            "builder", "child", "own"), "builder")("exited")
        await self.runtime.returns.drain()

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])

    async def test_a_requester_that_left_is_not_rung(self):
        await self.say("lead", "@builder render page one")
        self.db.set_attachment_status("lead", "detached", "own")
        await self.turn("builder", "Done.")

        self.assertEqual(self.adapters["lead"].bodies(), [])

    async def test_an_api_hand_off_settles_the_turn_like_speech(self):
        await self.say("lead", "@sub take page one")
        await self.presence.began("child", "sub")
        self.runtime.returns.note_spoke("sub", "@lead accepted, report 7 filed")
        await self.presence.ended("child", "sub")
        await self.runtime.returns.drain()

        self.assertEqual([b for b in self.adapters["lead"].bodies() if b.startswith("↩")], [])

    async def test_a_forgotten_attachment_owes_nothing(self):
        await self.say("lead", "@builder render page one")
        await self.presence.began("child", "builder")
        await self.presence.ended("child", "builder")
        self.presence.forget("builder")

        self.assertEqual(self.runtime.returns.requesters, {})
        self.assertEqual(self.runtime.returns.pending, {})


class ExcerptTest(unittest.TestCase):
    def test_a_quoted_mention_cannot_ring_anyone(self):
        self.assertEqual(excerpt("@person  PR is\nup"), "＠person PR is up")

    def test_long_speech_is_cut_with_an_ellipsis(self):
        text = excerpt("word " * 100)
        self.assertLessEqual(len(text), 280)
        self.assertTrue(text.endswith("…"))

    def test_nothing_said_is_empty(self):
        self.assertEqual(excerpt(None), "")


class AddresseesTest(unittest.TestCase):
    def test_the_leading_run_names_the_addressees(self):
        from partyline.mentions import addressees

        self.assertEqual(addressees("@lead please have @worker build it"), {"lead"})
        self.assertEqual(addressees("@a, @b and @c: files are present"), {"a", "b", "c"})
        self.assertEqual(addressees("@a — @b — go"), {"a", "b"})

    def test_without_a_leading_run_every_mention_is_addressed(self):
        from partyline.mentions import addressees

        self.assertEqual(addressees("Done. @lead please review"), {"lead"})
        self.assertEqual(addressees("Suite green; @a and @b may proceed"), {"a", "b"})

    def test_no_mentions_means_nobody(self):
        from partyline.mentions import addressees

        self.assertEqual(addressees("just thinking aloud"), set())


class DeferredReturnTest(ReturnPathTest):
    """A return rings only a requester that is waiting."""

    async def test_a_working_requester_is_not_interrupted(self):
        await self.say("sub", "@lead acknowledged, repairing now")  # sub is mid-turn
        await self.presence.began("child", "sub")
        await self.turn("lead", "Holding; nothing in flight.")

        self.assertEqual([b for b in self.adapters["sub"].bodies() if b.startswith("↩")], [])
        self.assertEqual(len(self.runtime.returns.deferred.get("sub", [])), 1)

    async def test_the_deferred_notice_lands_when_the_requester_ends_quietly(self):
        await self.turn("sub", "@lead which style do you want?")  # asked, then went idle
        await self.human("child", "@sub keep going meanwhile")
        await self.presence.began("child", "sub")  # working again when the answer comes
        await self.turn("lead", "Holding; nothing in flight.")
        await self.say("sub", "Repair done.")
        await self.presence.ended("child", "sub")
        await self.runtime.returns.drain()

        [notice] = [b for b in self.adapters["sub"].bodies() if b.startswith("↩")]
        self.assertIn("lead on line «Parent» ended its turn", notice)
        self.assertIn("last said: «Holding; nothing in flight.»", notice)
        self.assertEqual(self.runtime.returns.deferred, {})

    async def test_a_hand_off_by_the_requester_supersedes_the_deferred_notice(self):
        await self.say("sub", "@lead acknowledged, repairing now")
        await self.presence.began("child", "sub")
        await self.turn("lead", "Holding; nothing in flight.")
        await self.say("sub", "@lead repair done, please review")
        await self.presence.ended("child", "sub")
        await self.runtime.returns.drain()

        self.assertEqual([b for b in self.adapters["sub"].bodies() if b.startswith("↩")], [])
        self.assertEqual(self.runtime.returns.deferred, {})

    async def test_forgetting_a_requester_drops_what_it_was_owed(self):
        await self.say("sub", "@lead acknowledged, repairing now")
        await self.presence.began("child", "sub")
        await self.turn("lead", "Holding; nothing in flight.")
        self.presence.forget("sub")

        self.assertEqual(self.runtime.returns.deferred, {})

    async def test_private_return_notice_is_delivered_to_captain_exactly_once(self):
        await self.presence.began("parent", "lead")
        notice = await post_private(
            self.runtime,
            "parent",
            "system",
            "system",
            "↩ @lead — sub on line «Child» ended its turn without handing off",
            audience="lead",
            source=("sub", "child"),
        )
        self.presence.queue.hold("lead", [notice])
        assignment = await self.human("parent", "@lead assigning next task")
        await self.runtime.deliver_pending(
            "parent", self.db.get_attachment("lead"), self.runtime.live["lead"]
        )
        lead_seen = self.db.get_attachment("lead")["last_seen"]
        self.assertGreaterEqual(lead_seen, assignment["id"])

        await self.say("lead", "Acknowledged assignment.")
        await self.presence.ended("parent", "lead")
        await self.runtime.returns.drain()

        notices = [b for b in self.adapters["lead"].bodies() if b.startswith("↩")]
        self.assertEqual(len(notices), 1)
        self.assertEqual(self.presence.queue.held_count("lead"), 0)


class ApiEchoTest(Tree):
    async def test_a_tailed_twin_of_an_api_post_is_dropped(self):
        posted = self.db.add_message("parent", "lead", "agent", "Hello — lead is connected.")
        self.db._exec("UPDATE messages SET source_attachment_id=?, source_conv_id=? WHERE id=?",
                      ("lead", "parent", posted["id"]))
        await self.say("lead", "Hello —  lead is connected.")

        self.assertEqual([m["body"] for m in self.line("parent")], ["Hello — lead is connected."])

    async def test_different_words_are_not_an_echo(self):
        posted = self.db.add_message("parent", "lead", "agent", "Hello — lead is connected.")
        self.db._exec("UPDATE messages SET source_attachment_id=? WHERE id=?", ("lead", posted["id"]))
        await self.say("lead", "Suite is green.")

        self.assertEqual(len(self.line("parent")), 2)

    async def test_another_process_saying_the_same_words_is_not_an_echo(self):
        posted = self.db.add_message("parent", "lead", "agent", "Standing by.")
        self.db._exec("UPDATE messages SET source_attachment_id=? WHERE id=?", ("lead", posted["id"]))
        await self.say("worker", "Standing by.")

        self.assertEqual(len(self.line("parent")), 2)


class ColonAddressTest(Tree):
    async def test_a_handle_with_a_colon_at_line_start_rings_that_process(self):
        await self.say("lead", "worker: run the suite and report back")

        self.assertEqual(self.adapters["worker"].bodies(), ["worker: run the suite and report back"])

    async def test_a_label_that_is_nobody_rings_nobody(self):
        await self.say("lead", "Status: green, nothing pending")

        self.assertEqual(self.adapters["worker"].delivered, [])
        self.assertEqual(self.notices("parent"), [])

    async def test_the_colon_form_makes_a_requester_and_settles_a_turn(self):
        await self.say("lead", "worker: run the suite")
        await self.presence.began("parent", "worker")
        await self.say("worker", "Green.")
        await self.presence.ended("parent", "worker")
        await self.runtime.returns.drain()
        self.assertEqual(
            len([b for b in self.adapters["lead"].bodies() if b.startswith("↩")]), 1)

        await self.say("lead", "worker: now the lint")
        await self.presence.began("parent", "worker")
        await self.say("worker", "lead: lint is clean")
        await self.presence.ended("parent", "worker")
        await self.runtime.returns.drain()
        self.assertEqual(
            len([b for b in self.adapters["lead"].bodies() if b.startswith("↩")]), 1)
