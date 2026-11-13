"""A process that reached its compaction limit is replaced by a fresh instance of itself.

The fixture is a long-lived instance, not a clean tree: hundreds of retired lines
with their own processes and compaction history sit in the database, and a leftover
transcript from an earlier session of the same attachment sits on disk.
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline import compaction_rotation as rotation
from partyline import resource_budget
from partyline.adapters.base import Adapter
from partyline.compaction_events import bump_turn, note_hook_compaction
from partyline.line_notes import read_notes, write_notes
from partyline.rebrief import render_rebrief
from tests.orchestrator_fixture import TaskFixture

HANDOFF = "STATE: slice 2 of 3 done. NEXT: run the gates. SHA abc1234 in /work/tree"


class RotationFixture(TaskFixture):
    def setUp(self):
        super().setUp()
        from partyline.presence import Presence

        self.presence = Presence(self.runtime)
        self.starts = []
        self.sleeps = []
        for target, value in (("sleep", self.nap),):
            patcher = patch.object(rotation, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db.save_preset("boss", "boss", "boss", "fake", "fake-boss", can_manage=True)
        self.db._exec("UPDATE attachments SET command=?, preset='boss' WHERE id='captain'",
                      ('["fake-boss"]',))
        self.db.add_attachment("worker", "root", "worker", "fake", ["fake"], self.repo, "w1")
        self.db._exec("UPDATE attachments SET preset='builder' WHERE id='worker'")
        self.retired_lines(300)
        self.go_live("captain")
        self.go_live("worker")

    async def nap(self, seconds):
        self.sleeps.append(seconds)

    def retired_lines(self, count):
        """Hundreds of finished lines, each with a process that compacted in its day."""
        now = time.time()
        for index in range(count):
            line = f"old-{index}"
            self.db.create_conversation(line, f"Old {index}")
            self.db.add_attachment(f"old-att-{index}", line, f"old{index}", "fake", ["fake"],
                                   self.repo, f"old-owner-{index}")
            self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (f"old-att-{index}",))
            self.db._exec("UPDATE conversations SET archived_at=? WHERE id=?", (now, line))
            for owner in ("old-owner-a", "old-owner-b", "old-owner-c"):
                self.db._exec(
                    "INSERT INTO compaction_events(attachment_id,runtime_owner,trigger,turn,created_at)"
                    " VALUES(?,?,?,?,?)", (f"old-att-{index}", owner, "auto", 50, now))
        # the live worker's earlier activations compacted a lot, under other owners
        for owner in ("w-old-1", "w-old-2", "w-old-3", "w-old-4"):
            self.db._exec(
                "INSERT INTO compaction_events(attachment_id,runtime_owner,trigger,turn,created_at)"
                " VALUES('worker',?,'manual',1,?)", (owner, now))

    def go_live(self, ident):
        att = self.db.get_attachment(ident)
        self.db.set_attachment_status(ident, "running", att["runtime_owner"])

        async def stop():
            self.db.set_attachment_status(ident, "exited", att["runtime_owner"])

        self.runtime.live[ident] = SimpleNamespace(
            att=att, stop=stop, proc=None, deliver=AsyncMock(return_value=True))

    async def start(self, att, **kwargs):
        self.starts.append((dict(att), kwargs))
        self.db.set_attachment_status(att["id"], "running", att["runtime_owner"])
        self.go_live(att["id"])
        return self.db.get_attachment(att["id"])

    async def compact(self, ident, trigger="auto"):
        return await note_hook_compaction(self.runtime, self.db.get_attachment(ident), trigger)

    async def turn(self, ident):
        att = self.db.get_attachment(ident)
        owner = att["runtime_owner"]
        bump_turn(self.db, ident, owner)
        await self.presence.began(att["conv_id"], ident, owner=owner)
        await self.presence.ended(att["conv_id"], ident, owner=owner)
        await rotation.drain()

    def asks(self, ident):
        return [m for m in self.db.list_messages("root")
                if m.get("audience_attachment_id") == ident and "hand-off note" in m["body"]]

    def read_ask(self, ident):
        """The process pasted and read the ask: its cursor moves past it."""
        att = self.db.get_attachment(ident)
        self.db.set_last_seen(ident, self.asks(ident)[-1]["id"], att["runtime_owner"])

    def notices(self, text):
        return [m["body"] for m in self.db.list_messages("root")
                if text in m["body"] and not m.get("audience_attachment_id")]

    def row_of(self, ident):
        return self.db.get_attachment(ident)


class LimitReachedTest(RotationFixture):
    async def test_two_compactions_ask_at_turn_end_then_rotate_on_the_note(self):
        await self.compact("worker")
        await self.turn("worker")
        self.assertEqual(self.asks("worker"), [])  # one compaction: nothing yet
        await self.compact("worker")
        self.assertEqual(self.starts, [])  # never mid-turn
        await self.turn("worker")  # the turn the compaction landed in ends: ask once
        self.assertEqual(len(self.asks("worker")), 1)
        self.assertIn("at most 4000", self.asks("worker")[0]["body"])
        self.assertEqual(self.starts, [])
        await self.turn("worker")  # ended without reading the ask: not yet
        self.assertEqual(len(self.asks("worker")), 1)
        self.assertEqual(self.starts, [])
        before = self.row_of("worker")
        self.read_ask("worker")
        write_notes(self.db, "root", "attachment", HANDOFF, "worker")
        await self.turn("worker")
        self.assertEqual(len(self.starts), 1)
        started, kwargs = self.starts[0]
        after = self.row_of("worker")
        self.assertEqual((after["id"], after["name"], after["conv_id"]), ("worker", "worker", "root"))
        self.assertNotEqual(after["runtime_owner"], before["runtime_owner"])
        self.assertIsNone(after["cli_session"])
        self.assertTrue(after["session_pin"] and after["session_pin"] != "worker")
        self.assertTrue(kwargs["fresh"])
        self.assertEqual(kwargs["staffing_role"], "implementer")
        self.assertTrue(started["fresh_resume_now"])
        self.assertIn(HANDOFF, kwargs["checkpoint"])
        self.assertIn("rotated after 2 compactions, limit 2", kwargs["checkpoint"])
        self.assertEqual(self.sleeps, [rotation.GRACE_SECONDS])
        self.assertEqual(rotation.armed_table(self.runtime), {})
        self.assertEqual(len(self.notices("@worker rotated to a fresh instance")), 1)
        self.assertIn("briefed from its hand-off note", self.notices("rotated")[0])

    async def test_a_process_that_ignores_the_ask_is_rotated_at_its_next_turn_end(self):
        await self.compact("worker")
        await self.compact("worker")
        await self.turn("worker")
        self.read_ask("worker")
        write_notes(self.db, "root", "attachment", "an old note from long ago", "worker")
        self.db._exec("UPDATE line_notes SET updated_at=1 WHERE attachment_id='worker'")
        await self.turn("worker")
        self.assertEqual(len(self.starts), 1)
        self.assertIn("an old note from long ago", self.starts[0][1]["checkpoint"])
        self.assertIn("wrote no hand-off note", self.notices("rotated")[0])

    async def test_nothing_rotates_while_the_ask_is_still_unread(self):
        await self.compact("worker")
        await self.compact("worker")
        await self.turn("worker")
        for _ in range(3):
            await self.turn("worker")
        self.assertEqual(self.starts, [])
        self.assertIn("worker", rotation.armed_table(self.runtime))

    async def test_a_full_handoff_note_survives_long_notes_and_a_long_topic(self):
        note = "H" * 3990 + " END"
        write_notes(self.db, "root", "attachment", note, "worker")
        write_notes(self.db, "root", "line", "L" * 3990, "")
        write_notes(self.db, "root", "tree", "T" * 3990, "")
        self.db.set_topic("root", "topic " * 3000)
        await self.compact("worker")
        await self.compact("worker")
        await self.turn("worker")
        self.read_ask("worker")
        await self.turn("worker")
        checkpoint = self.starts[0][1]["checkpoint"]
        self.assertIn(note, checkpoint)
        self.assertLess(checkpoint.index(note), checkpoint.index("L" * 100))
        self.assertLess(len(checkpoint), rotation.BRIEFING_LIMIT + 200)

    async def test_the_second_rotation_in_the_same_attachments_life(self):
        for _ in range(2):
            await self.compact("worker")
        await self.turn("worker")
        self.read_ask("worker")
        await self.turn("worker")
        first_pin = self.row_of("worker")["session_pin"]
        self.assertEqual(len(self.starts), 1)
        # the fresh activation's compaction count starts over: one is not the limit
        await self.compact("worker")
        await self.turn("worker")
        self.assertEqual(len(self.asks("worker")), 1)
        await self.compact("worker")
        await self.turn("worker")
        self.assertEqual(len(self.asks("worker")), 2)
        self.read_ask("worker")
        await self.turn("worker")
        self.assertEqual(len(self.starts), 2)
        self.assertNotEqual(self.row_of("worker")["session_pin"], first_pin)
        self.assertEqual(len(self.notices("@worker rotated to a fresh instance")), 2)

    async def test_an_arm_left_by_an_earlier_activation_is_dropped(self):
        await self.compact("worker")
        await self.compact("worker")
        self.db._exec("UPDATE attachments SET runtime_owner='w-new' WHERE id='worker'")
        self.runtime.live["worker"].att["runtime_owner"] = "w-new"
        await self.turn("worker")
        self.assertEqual(self.asks("worker"), [])
        self.assertEqual(rotation.armed_table(self.runtime), {})


class ThrashAndLimitSettingsTest(RotationFixture):
    async def test_thrash_rotates_below_the_limit(self):
        self.db.set_setting("max_compactions_per_process", "9")
        for _ in range(3):
            bump_turn(self.db, "worker", "w1")
            await self.compact("worker")
        armed = rotation.armed_table(self.runtime)["worker"]
        self.assertIn("thrashing", armed.reason)
        self.assertEqual(self.db._exec("SELECT COUNT(*) n FROM messages WHERE body LIKE '%is thrashing%'"
                                       ).fetchone()["n"], 0)  # the captain need not act

    async def test_limit_zero_turns_rotation_off_and_the_ring_remains(self):
        self.db.set_setting("max_compactions_per_process", "0")
        for _ in range(5):
            bump_turn(self.db, "worker", "w1")
            await self.compact("worker")
        self.assertEqual(rotation.armed_table(self.runtime), {})
        await self.turn("worker")
        self.assertEqual((self.asks("worker"), self.starts), ([], []))
        rings = [m for m in self.db.list_messages("root") if "is thrashing" in m["body"]]
        self.assertEqual(len(rings), 1)

    async def test_a_preset_override_beats_the_instance_setting(self):
        self.db._exec("UPDATE presets SET max_compactions=1 WHERE name='builder'")
        await self.compact("worker")
        self.assertIn("worker", rotation.armed_table(self.runtime))
        rotation.armed_table(self.runtime).clear()
        self.db._exec("UPDATE presets SET max_compactions=0 WHERE name='builder'")
        for _ in range(4):
            await self.compact("worker")
        self.assertEqual(rotation.armed_table(self.runtime), {})
        self.db._exec("UPDATE presets SET max_compactions=NULL WHERE name='builder'")
        await self.compact("worker")  # inherits the default of 2
        self.assertIn("worker", rotation.armed_table(self.runtime))


class RolesTest(RotationFixture):
    async def test_a_captain_keeps_captainship_and_its_pack_state(self):
        self.db.create_conversation("child", "Child")
        write_notes(self.db, "root", "attachment", HANDOFF, "captain")
        self.db._exec("UPDATE presets SET can_manage=0 WHERE name='boss'")
        await self.compact("captain")
        await self.compact("captain")
        await self.turn("captain")
        self.read_ask("captain")
        await self.turn("captain")
        _started, kwargs = self.starts[0]
        after = self.row_of("captain")
        self.assertEqual(after["is_lead"], 1)
        self.assertEqual(kwargs["staffing_role"], "captain")
        self.assertIn(HANDOFF, kwargs["checkpoint"])
        self.assertIn("captain", kwargs["checkpoint"].lower())
        leads = [a for a in self.db.list_attachments("root") if a["is_lead"]]
        self.assertEqual([a["id"] for a in leads], ["captain"])

    async def test_task_implementer_keeps_its_task_and_preset(self):
        row = await self.create()
        ident = row["implementer_id"]
        self.go_live(ident)
        self.db._exec("UPDATE presets SET implements=0 WHERE name='builder'")
        self.starts.clear()  # the task's own first staffing is not a rotation
        await self.compact(ident)
        await self.compact(ident)
        await self.presence_turn(ident)
        self.read_task_ask(ident)
        await self.presence_turn(ident)
        _started, kwargs = self.starts[0]
        self.assertEqual((kwargs["staffing_role"], kwargs["staffing_preset"]),
                         ("implementer", "builder"))
        self.assertEqual(self.row()["implementer_id"], ident)

    async def test_a_full_handoff_note_survives_a_task_pack_with_a_very_long_goal(self):
        row = await self.create()
        ident = row["implementer_id"]
        for size in (5000, 30000):
            self.db._exec("UPDATE conversations SET goal=? WHERE id=?", ("G" * size, row["conv_id"]))
            note = "S" * (4000 - 40) + " NEXT STEP: ship sha abc1234"
            write_notes(self.db, row["conv_id"], "attachment", note, ident)
            text = render_rebrief(self.db, self.db.get_attachment(ident), limit=rotation.BRIEFING_LIMIT,
                                  handoff=True, reason="rotated after 2 compactions, limit 2")
            self.assertIn(note, text, size)
            self.assertLessEqual(len(text), rotation.BRIEFING_LIMIT)
            self.assertIn("Task line pack", text)

    async def test_a_handoff_quoting_the_captain_pointer_is_never_edited_to_fit(self):
        from partyline.role_delivery import briefing_pointer

        pointer = briefing_pointer("root")
        note = pointer + "\nSTATE " + "n" * (3900 - len(pointer)) + " NEXT STEP: ship abc1234"
        write_notes(self.db, "root", "attachment", note, "captain")
        write_notes(self.db, "root", "line", "L" * 3990, "")
        write_notes(self.db, "root", "tree", "T" * 3990, "")
        self.db._exec("UPDATE conversations SET goal=? WHERE id='root'", ("G" * 20000,))
        self.db.add_message("root", "greg", "human", "@boss " + "a" * 7900)
        text = render_rebrief(self.db, self.db.get_attachment("captain"), limit=rotation.BRIEFING_LIMIT,
                              handoff=True, reason="rotated after 2 compactions, limit 2")
        self.assertIn(note.strip(), text)
        self.assertLessEqual(len(text), rotation.BRIEFING_LIMIT)
        self.assertEqual(text.count(pointer), 2, (len(text), len(pointer)))  # the note quote and the reminder

    async def test_task_reviewer_keeps_its_role(self):
        row = await self.create()
        self.db._exec("UPDATE task_reviews SET status='in_review' WHERE conv_id=?", (self.conv_id,))
        self.db._exec("UPDATE task_reviews SET reviewer_id='rev' WHERE conv_id=?", (self.conv_id,))
        self.db.add_attachment("rev", self.conv_id, "review-x", "fake", ["fake"], self.repo, "r1")
        self.db._exec("UPDATE attachments SET preset='inspector' WHERE id='rev'")
        self.starts.clear()
        self.go_live("rev")
        await self.compact("rev")
        await self.compact("rev")
        await self.presence_turn("rev")
        self.read_task_ask("rev")
        await self.presence_turn("rev")
        _started, kwargs = self.starts[0]
        self.assertEqual((kwargs["staffing_role"], kwargs["staffing_preset"]),
                         ("reviewer", "inspector"))
        self.assertEqual(self.row()["reviewer_id"], "rev")
        self.assertEqual(row["implementer_id"], self.row()["implementer_id"])

    async def presence_turn(self, ident):
        att = self.db.get_attachment(ident)
        bump_turn(self.db, ident, att["runtime_owner"])
        await self.presence.began(att["conv_id"], ident, owner=att["runtime_owner"])
        await self.presence.ended(att["conv_id"], ident, owner=att["runtime_owner"])
        await rotation.drain()

    def read_task_ask(self, ident):
        att = self.db.get_attachment(ident)
        asks = [m for m in self.db.list_messages(att["conv_id"])
                if m.get("audience_attachment_id") == ident and "hand-off note" in m["body"]]
        self.db.set_last_seen(ident, asks[-1]["id"], att["runtime_owner"])

    async def test_a_helper_process_is_never_rotated(self):
        self.db.add_attachment("idle", "root", "idle-check", "raw", ["raw"], self.repo, "h1")
        self.go_live("idle")
        rotation.armed_table(self.runtime)["idle"] = rotation.Armed("h1", "test", 3, 2, asked_id=1)
        rotation.armed_table(self.runtime)["idle"].asked_at = 0
        self.db.set_last_seen("idle", 1, "h1")
        await self.turn("idle")
        self.assertEqual(self.starts, [])
        self.assertEqual(rotation.armed_table(self.runtime), {})


class GuardsTest(RotationFixture):
    async def reach_the_ask(self, ident="worker"):
        await self.compact(ident)
        await self.compact(ident)
        await self.turn(ident)
        self.read_ask(ident)

    async def test_a_pending_restart_request_defers_the_rotation(self):
        await self.reach_the_ask()
        self.runtime.restart_request = object()
        await self.turn("worker")
        self.assertEqual(self.starts, [])
        self.assertIn("worker", rotation.armed_table(self.runtime))
        self.runtime.restart_request = None
        await self.turn("worker")
        self.assertEqual(len(self.starts), 1)

    async def test_a_pending_handover_defers_the_rotation_for_either_party(self):
        await self.reach_the_ask("captain")
        self.db._exec(
            "INSERT INTO captain_handovers(id,conv_id,from_attachment_id,to_attachment_id,debrief,"
            "state,offered_at) VALUES('h','root','captain','worker','x','offered',?)", (time.time(),))
        await self.turn("captain")
        self.assertEqual(self.starts, [])
        self.db._exec("UPDATE captain_handovers SET state='cancelled'")
        await self.turn("captain")
        self.assertEqual(len(self.starts), 1)

    async def test_a_pending_handover_defers_the_rotation_of_its_receiving_side_too(self):
        await self.reach_the_ask("worker")
        self.db._exec(
            "INSERT INTO captain_handovers(id,conv_id,from_attachment_id,to_attachment_id,debrief,"
            "state,offered_at) VALUES('h','root','captain','worker','x','offered',?)", (time.time(),))
        await self.turn("worker")
        self.assertEqual(self.starts, [])
        self.db._exec("UPDATE captain_handovers SET state='cancelled'")
        await self.turn("worker")
        self.assertEqual(len(self.starts), 1)

    async def test_the_ask_itself_waits_for_a_pending_restart(self):
        self.runtime.restart_request = object()
        await self.compact("worker")
        await self.compact("worker")
        await self.turn("worker")
        self.assertEqual(self.asks("worker"), [])
        self.runtime.restart_request = None
        await self.turn("worker")
        self.assertEqual(len(self.asks("worker")), 1)

    async def test_a_turn_that_reopens_during_the_grace_cancels_this_attempt(self):
        await self.reach_the_ask()
        att = self.db.get_attachment("worker")

        async def reopen(_seconds):
            await self.presence.began("root", "worker", owner=att["runtime_owner"])

        with patch.object(rotation, "sleep", reopen):
            await self.turn("worker")
        self.assertEqual(self.starts, [])
        await self.presence.ended("root", "worker", owner=att["runtime_owner"])
        await rotation.drain()
        self.assertEqual(len(self.starts), 1)

    async def test_a_process_that_cannot_be_restarted_is_left_running(self):
        await self.reach_the_ask()
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='worker'", (os.path.join(self.repo, "missing"),))
        await self.turn("worker")
        self.assertEqual(self.starts, [])
        self.assertEqual(self.row_of("worker")["status"], "running")
        self.assertEqual(rotation.armed_table(self.runtime), {})
        self.assertEqual(len(self.notices("cannot be restarted")), 1)

    async def test_wakes_held_in_the_last_turn_go_out_when_the_detach_fails(self):
        await self.reach_the_ask()
        flush = AsyncMock(return_value=True)
        self.presence.queue.register_deliver("worker", flush)
        self.presence.queue.hold("worker", [{"id": 77}])
        with patch("partyline.line_process_routes.detach_attachment",
                   AsyncMock(side_effect=RuntimeError("busy"))):
            await self.turn("worker")
        self.assertEqual(self.row_of("worker")["status"], "running")
        flush.assert_awaited_once_with([77])

    async def test_a_start_that_fails_after_the_stop_is_reported_and_clears_the_arm(self):
        await self.reach_the_ask()
        self.start = AsyncMock(side_effect=RuntimeError("no pty"))
        with patch("partyline.server._start_attachment", self.start):
            await self.turn("worker")
        self.assertEqual(len(self.notices("rotation failed: no pty")), 1)
        self.assertNotIn("worker", rotation.armed_table(self.runtime))
        self.assertNotIn("worker", self.runtime.reattaching)

    async def test_a_detach_that_fails_keeps_the_process_and_retries_once(self):
        await self.reach_the_ask()
        failing = AsyncMock(side_effect=RuntimeError("busy"))
        with patch("partyline.line_process_routes.detach_attachment", failing):
            await self.turn("worker")
            self.assertIn("worker", rotation.armed_table(self.runtime))
            await self.turn("worker")
        self.assertEqual(failing.await_count, 2)
        self.assertNotIn("worker", rotation.armed_table(self.runtime))
        self.assertEqual(self.row_of("worker")["status"], "running")


class RealStartTest(RotationFixture):
    """Drive the production start path: only the CLI process itself is faked."""

    def setUp(self):
        super().setUp()
        self.adapters = []
        self.flushes = []
        patcher = patch("partyline.server._start_attachment", self.real_start)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_adapter(self, kind, att, post, on_status, on_cli_session=None):
        adapter = Adapter(att, post, on_status, on_cli_session)

        async def start():
            await on_status("running")

        async def stop():
            await on_status("detached")

        adapter.start, adapter.stop = start, AsyncMock(side_effect=stop)
        adapter.raw_deliver = adapter.deliver = AsyncMock(return_value=True)
        self.adapters.append(adapter)
        return adapter

    async def real_start(self, att, **kwargs):
        from partyline.attachment_start import start_attachment

        return await start_attachment(att, runtime=self.runtime, presence=self.presence,
                                      make_adapter=self.make_adapter,
                                      hook_url=lambda ident, owner: "http://127.0.0.1:1/hook", **kwargs)

    def hold_for_the_old_instance(self, *ids):
        self.presence.queue.register_deliver("worker", AsyncMock(return_value=True))
        self.presence.queue.hold("worker", [{"id": i} for i in ids])

    async def rotate_worker(self, note="", during=None):
        await self.compact("worker")
        await self.compact("worker")
        await self.turn("worker")
        self.read_ask("worker")
        if note:
            write_notes(self.db, "root", "attachment", note, "worker")
        if during:
            during()
        self.before = len(self.public())
        await self.turn("worker")

    def public(self):
        return [m["body"] for m in self.db.list_messages("root")
                if m["sender_type"] == "system" and not m.get("audience_attachment_id")
                and "worker" in m["body"]]

    async def test_plain_process_without_captain_or_fast_trait_rotates(self):
        self.db._exec("UPDATE attachments SET is_lead=0 WHERE id='captain'")
        self.db._exec("DELETE FROM attachments WHERE id='captain'")
        self.db._exec("UPDATE presets SET implements=0 WHERE name='builder'")
        from fastapi import HTTPException
        from partyline.preset_roles import require_resume
        with self.assertRaises(HTTPException) as error:
            require_resume(self.db, "worker")
        self.assertEqual(error.exception.status_code, 403)
        await self.rotate_worker()
        self.assertEqual(self.row_of("worker")["status"], "running")
        self.assertEqual(len(self.adapters), 1)

    async def test_plain_process_rotates_when_recorded_preset_is_missing_or_ambiguous(self):
        self.db.save_preset("duplicate", "duplicate", "Builder", "fake", "fake", implements=True)
        for name in ("missing", "BUILDER"):
            self.db._exec("UPDATE attachments SET preset=? WHERE id='worker'", (name,))
            await self.rotate_worker()
            self.assertEqual(self.row_of("worker")["status"], "running")
        self.assertEqual(len(self.adapters), 2)

    async def test_task_implementer_rotates_after_trait_removed_through_real_start(self):
        row = await self.create()
        ident = row["implementer_id"]
        self.go_live(ident)
        self.db._exec("UPDATE presets SET implements=0 WHERE name='builder'")
        for _ in range(2):
            await self.compact(ident)
        await self.turn(ident)
        att = self.row_of(ident)
        ask = next(m for m in self.db.list_messages(att["conv_id"])
                   if m.get("audience_attachment_id") == ident and "hand-off note" in m["body"])
        self.db.set_last_seen(ident, ask["id"], att["runtime_owner"])
        await self.turn(ident)
        self.assertEqual(self.row_of(ident)["status"], "running")
        self.assertEqual(self.adapters[-1].att["id"], ident)

    async def test_the_fresh_instance_is_told_to_continue_and_the_line_hears_one_notice(self):
        await self.rotate_worker(HANDOFF)
        fresh = self.adapters[-1]
        self.assertEqual(fresh.att["id"], "worker")
        self.assertTrue(fresh.att["fresh_resume_now"])
        briefing = fresh.briefing()
        self.assertIn("continue the work now", briefing)
        self.assertNotIn("wait for the first @mention", briefing)
        self.assertIn(HANDOFF, briefing)
        said = self.public()[self.before:]
        self.assertEqual(len(said), 1, said)
        self.assertIn("@worker rotated to a fresh instance — 2 compactions, limit 2; briefed from", said[0])

    async def test_a_wake_queued_between_stop_and_start_reaches_the_fresh_instance(self):
        from partyline.message_routing import route_message

        seen = {}
        real_claim = resource_budget.claim_resume

        async def claim_after_a_mention(db, att_id, owner, lease, **kwargs):
            message = self.db.add_message("root", "greg", "human", "@worker please also check X")
            self.runtime.route_mentions = AsyncMock()
            await route_message(self.runtime, "root", message)
            seen["unreachable"] = self.notices("not attached") + self.notices("unreachable")
            return await real_claim(db, att_id, owner, lease, **kwargs)

        with patch.object(resource_budget, "claim_resume", claim_after_a_mention):
            await self.rotate_worker()
        self.assertEqual(seen["unreachable"], [])
        delivered = self.adapters[-1].raw_deliver
        self.assertEqual(delivered.await_count, 1)
        bodies = [m["body"] for m in delivered.await_args.args[0]]
        self.assertEqual(bodies.count("@worker please also check X"), 1)
        self.assertEqual(bodies[-1], "@worker please also check X")

    async def test_a_wake_held_in_the_last_turn_is_not_discarded_with_the_old_instance(self):
        def mention_during_the_last_turn():
            message = self.db.add_message("root", "greg", "human", "@worker held while you worked")
            self.hold_for_the_old_instance(message["id"])

        await self.rotate_worker(during=mention_during_the_last_turn)
        self.assertEqual(self.notices("held mention"), [])
        self.assertEqual(self.notices("undelivered"), [])
        self.assertEqual(self.presence.queue.held_count("worker"), 0)
        delivered = self.adapters[-1].raw_deliver
        bodies = [m["body"] for call in delivered.await_args_list for m in call.args[0]]
        self.assertEqual(bodies.count("@worker held while you worked"), 1)

    async def test_a_wake_the_old_instance_persisted_as_skipped_is_flushed_to_the_fresh_one(self):
        message = self.db.add_message("root", "greg", "human", "@worker skipped by the CLI")
        owner = self.row_of("worker")["runtime_owner"]
        self.db.set_last_seen("worker", message["id"], owner)
        await self.db.queue_delivery_ids("worker", [message["id"]], owner)
        await self.rotate_worker()
        delivered = self.adapters[-1].raw_deliver
        bodies = [m["body"] for call in delivered.await_args_list for m in call.args[0]]
        self.assertEqual(bodies.count("@worker skipped by the CLI"), 1)
        self.assertEqual(self.db.queued_delivery_ids("worker"), [])

    async def test_wakes_held_in_the_last_turn_go_out_when_the_rotation_is_abandoned(self):
        flush = AsyncMock(return_value=True)
        self.presence.queue.register_deliver("worker", flush)
        self.presence.queue.hold("worker", [{"id": 41}])
        await self.compact("worker")
        await self.compact("worker")
        await self.turn("worker")
        self.read_ask("worker")
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='worker'", (os.path.join(self.repo, "missing"),))
        await self.turn("worker")
        self.assertEqual(self.adapters, [])
        flush.assert_awaited_once_with([41])
        self.assertEqual(self.presence.queue.held_count("worker"), 0)


class LeftoversOnDiskTest(RotationFixture):
    async def test_a_leftover_session_of_this_attachment_is_never_reused(self):
        from partyline.adapters.bundled.claude.adapter import PartylineAdapter

        config = os.path.join(self.directory.name, "claude")
        projects = os.path.join(config, "projects", "-some-dir")
        os.makedirs(projects)
        open(os.path.join(projects, "worker.jsonl"), "w").close()  # the old session
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config}):
            att = self.db.get_attachment("worker")
            att.update(command=["claude"], resume=False, hook_url=None)
            fresh_cmd = PartylineAdapter(att, AsyncMock(), AsyncMock()).build_command()
            self.assertEqual(fresh_cmd[fresh_cmd.index("--session-id") + 1], "worker")  # unrotated
            self.db._exec("UPDATE attachments SET session_pin='pin-1' WHERE id='worker'")
            att = self.db.get_attachment("worker")
            att.update(command=["claude"], resume=False, hook_url=None)
            fresh_cmd = PartylineAdapter(att, AsyncMock(), AsyncMock()).build_command()
            self.assertEqual(fresh_cmd[fresh_cmd.index("--session-id") + 1], "pin-1")
            self.assertFalse(Adapter.session_exists(att))  # no stored cli_session
            self.assertFalse(PartylineAdapter.session_exists(att))  # the leftover is not ours
            att["resume"] = True
            resumed = PartylineAdapter(att, AsyncMock(), AsyncMock()).build_command()
            self.assertEqual(resumed[resumed.index("--resume") + 1], "pin-1")
        self.assertEqual(read_notes(self.db, "root", "attachment", "worker")["notes"], "")
