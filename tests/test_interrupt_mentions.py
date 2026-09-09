"""`@!name` parsing, policy, and Antigravity's confirmed interrupt."""

import asyncio
import time
import unittest

from datetime import UTC, datetime

from partyline.adapters.bundled.antigravity.interrupt import (
    ESCAPE,
    interrupt as antigravity_interrupt,
    is_interrupt_record,
    record_key,
)
from partyline.interrupts import (
    PendingInterrupts,
    interrupt_for,
    supports_interrupt,
)
from partyline.mentions import interrupt_names, mentioned_names


class BangParsingTest(unittest.TestCase):
    def test_a_bang_mention_still_names_the_handle(self):
        # The bang adds an interrupt; it must never cost the delivery.
        self.assertEqual(mentioned_names("please @!sol stop"), {"sol"})
        self.assertEqual(interrupt_names("please @!sol stop"), {"sol"})

    def test_a_plain_mention_carries_no_interrupt(self):
        self.assertEqual(mentioned_names("hi @sol"), {"sol"})
        self.assertEqual(interrupt_names("hi @sol"), set())

    def test_both_forms_can_appear_in_one_message(self):
        body = "@!sol drop that, @terra keep going"

        self.assertEqual(mentioned_names(body), {"sol", "terra"})
        self.assertEqual(interrupt_names(body), {"sol"})

    def test_several_processes_can_be_interrupted_by_one_message(self):
        body = "@!sol @terra @!luna"

        self.assertEqual(mentioned_names(body), {"sol", "terra", "luna"})
        self.assertEqual(interrupt_names(body), {"sol", "luna"})

    def test_a_handle_named_both_ways_is_interrupted_once(self):
        # A set, not a count: the routing loop visits each attachment once and
        # the pending guard allows one interrupt, so repeating the handle
        # cannot multiply the Esc presses.
        for body in ("@!sol and @sol again", "@sol then @!sol"):
            with self.subTest(body=body):
                self.assertEqual(mentioned_names(body), {"sol"})
                self.assertEqual(interrupt_names(body), {"sol"})

    def test_all_is_never_interruptible(self):
        # `@!all` rings the room like `@all`, but stopping every process at
        # once is a blast radius nobody asked for.
        self.assertEqual(mentioned_names("@!all"), {"all"})
        self.assertEqual(interrupt_names("@!all"), set())

    def test_zero_width_characters_between_the_sigil_and_the_name(self):
        # A copied mention can carry a joiner. A reader sees @!sol; so must we.
        self.assertEqual(interrupt_names("@​!​sol"), {"sol"})

    def test_trailing_punctuation_belongs_to_the_sentence(self):
        self.assertIn("sol", interrupt_names("@!sol."))

    def test_an_email_address_is_not_an_interrupt(self):
        self.assertEqual(interrupt_names("write to a@b.com"), set())

    def test_a_bare_bang_names_nothing(self):
        for body in ("@!", "@! sol", "hello!", "@!!sol"):
            with self.subTest(body=body):
                self.assertEqual(interrupt_names(body), set())


class Adapter:
    """The narrow adapter surface the interrupt policy touches."""

    def __init__(self, confirmed=True, raises=False):
        self.confirmed = confirmed
        self.raises = raises
        self.calls = 0

    async def interrupt(self):
        self.calls += 1
        if self.raises:
            raise RuntimeError("pty is gone")
        return self.confirmed


class Uninterruptible:
    pass


class InterruptPolicyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.attachment = {"id": "att-1", "name": "sol", "adapter": "antigravity",
                           "runtime_owner": "owner-1"}
        self.pending = PendingInterrupts()

    def test_support_is_a_published_method_not_a_manifest_promise(self):
        self.assertTrue(supports_interrupt(Adapter()))
        self.assertFalse(supports_interrupt(Uninterruptible()))

    async def test_a_confirmed_interrupt_says_so(self):
        adapter = Adapter(confirmed=True)

        outcome = await interrupt_for(self.attachment, adapter, pending=self.pending)

        self.assertEqual((outcome.attempted, outcome.confirmed), (True, True))
        self.assertIn("was interrupted", outcome.notice)

    async def test_an_unconfirmed_interrupt_does_not_claim_success(self):
        adapter = Adapter(confirmed=False)

        outcome = await interrupt_for(self.attachment, adapter, pending=self.pending)

        self.assertEqual((outcome.attempted, outcome.confirmed), (True, False))
        self.assertIn("did not confirm", outcome.notice)
        self.assertIn("may still be running", outcome.notice)

    async def test_an_unsupported_adapter_is_named_along_with_its_kind(self):
        outcome = await interrupt_for(self.attachment, Uninterruptible(), pending=self.pending)

        self.assertEqual((outcome.attempted, outcome.confirmed), (False, False))
        self.assertIn("@sol cannot be interrupted", outcome.notice)
        self.assertIn("antigravity", outcome.notice)
        self.assertIn("delivered as an ordinary mention", outcome.notice)

    async def test_a_failing_interrupt_is_reported_rather_than_raised(self):
        outcome = await interrupt_for(self.attachment, Adapter(raises=True), pending=self.pending)

        self.assertEqual((outcome.attempted, outcome.confirmed), (True, False))
        self.assertIn("could not be interrupted", outcome.notice)

    async def test_only_one_interruption_is_in_flight_at_a_time(self):
        released = asyncio.Event()
        adapter = Adapter()

        async def slow():
            adapter.calls += 1
            await released.wait()
            return True

        adapter.interrupt = slow
        first = asyncio.create_task(
            interrupt_for(self.attachment, adapter, pending=self.pending)
        )
        await asyncio.sleep(0)

        second = await interrupt_for(self.attachment, adapter, pending=self.pending)
        released.set()
        await first

        self.assertFalse(second.attempted)
        self.assertIn("already has an interruption in flight", second.notice)
        self.assertEqual(adapter.calls, 1, "a second bang must not stack a second Esc")

    async def test_a_finished_interrupt_releases_the_slot(self):
        adapter = Adapter()

        await interrupt_for(self.attachment, adapter, pending=self.pending)
        again = await interrupt_for(self.attachment, adapter, pending=self.pending)

        self.assertTrue(again.attempted)
        self.assertEqual(adapter.calls, 2)

    async def test_a_replaced_activation_is_not_held_by_the_old_ones_flag(self):
        self.pending.claim("att-1", "owner-1")
        replaced = {**self.attachment, "runtime_owner": "owner-2"}

        outcome = await interrupt_for(replaced, Adapter(), pending=self.pending)

        self.assertTrue(outcome.attempted)

    async def test_an_old_activation_finishing_late_cannot_free_the_new_ones_slot(self):
        # The race: a slow interrupt outlives its activation. It returns while
        # the replacement's own interrupt is still in flight, and releasing
        # blindly would free a slot that is legitimately held — letting a third
        # bang start a second concurrent Esc on the new process.
        def blocker():
            gate = asyncio.Event()
            adapter = Adapter()

            async def slow():
                adapter.calls += 1
                await gate.wait()
                return True

            adapter.interrupt = slow
            return adapter, gate

        old, old_gate = blocker()
        new, new_gate = blocker()

        stale = asyncio.create_task(
            interrupt_for(self.attachment, old, pending=self.pending))
        await asyncio.sleep(0)

        replaced = {**self.attachment, "runtime_owner": "owner-2"}
        current = asyncio.create_task(
            interrupt_for(replaced, new, pending=self.pending))
        await asyncio.sleep(0)

        # The old activation returns while the new one is still interrupting.
        old_gate.set()
        await stale

        self.assertEqual(
            self.pending.owners.get("att-1"), "owner-2",
            "the old activation's release must not clear the new one's claim",
        )
        blocked = await interrupt_for(replaced, new, pending=self.pending)
        self.assertFalse(blocked.attempted)
        self.assertEqual(new.calls, 1, "no second concurrent Esc on the new process")

        new_gate.set()
        await current

    def test_release_only_gives_up_the_claim_it_made(self):
        self.pending.claim("att-1", None)

        self.pending.release("att-1", "someone-else")
        self.assertIn("att-1", self.pending.owners, "a foreign release is a no-op")

        # `None` is a real owner, not "unclaimed", so it must release itself.
        self.pending.release("att-1", None)
        self.assertNotIn("att-1", self.pending.owners)


def stamp(offset: float = 0.0) -> str:
    return datetime.fromtimestamp(time.time() + offset, UTC).isoformat()


def notice(offset: float = 0.0, step: int = 1) -> dict:
    return {"source": "SYSTEM", "type": "ERROR_MESSAGE", "created_at": stamp(offset),
            "step_index": step,
            "content": "Error: The stream was interrupted. Please continue the task."}


class FakePty:
    """The adapter surface `interrupt()` touches, with a transcript tail."""

    def __init__(self, alive=True, turn_open=False):
        self.alive_flag = alive
        self.written = []
        self.interrupt_confirmed = asyncio.Event()
        self.interrupt_since = None
        self.interrupt_records_used = set()
        self._turn_open = turn_open

    def alive(self):
        return self.alive_flag

    def write_terminal(self, data):
        self.written.append(data)

    def tail(self, record):
        """What the adapter's transcript handler does with one step."""
        if is_interrupt_record(record, self.interrupt_since, self.interrupt_records_used):
            self.interrupt_records_used.add(record_key(record))
            self.interrupt_confirmed.set()


class AntigravityInterruptTest(unittest.IsolatedAsyncioTestCase):
    def test_only_antigravitys_own_notice_counts_as_confirmation(self):
        real = {"source": "SYSTEM", "type": "ERROR_MESSAGE",
                "content": "Error: The stream was interrupted. Please continue the task "
                           "you were working on."}
        self.assertTrue(is_interrupt_record(real))
        # A planner response never carries a cancelled status — verified across
        # 28 transcripts — so nothing else may stand in for this record.
        for other in (
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "status": "CANCELLED"},
            {"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": "interrupted"},
            {"source": "SYSTEM", "type": "ERROR_MESSAGE", "content": "model output error"},
            "not a record",
            None,
        ):
            with self.subTest(record=other):
                self.assertFalse(is_interrupt_record(other))

    async def test_esc_is_written_and_the_transcript_confirms_it(self):
        pty = FakePty()

        async def confirm():
            await asyncio.sleep(0)
            pty.tail(notice())

        asyncio.create_task(confirm())
        confirmed = await antigravity_interrupt(pty, timeout=1, settle_timeout=1)

        self.assertTrue(confirmed)
        self.assertEqual(pty.written, [ESCAPE])

    async def test_a_notice_from_moments_earlier_does_not_confirm_this_esc(self):
        # The narrow case: two bangs a second apart. The first interruption's
        # notice reaches a lagging tail after the second Esc. Any tolerance in
        # the comparison is exactly the window it walks through.
        for age in (0.05, 0.5, 1.0, 1.9):
            with self.subTest(seconds_earlier=age):
                pty = FakePty()
                pty.interrupt_since = time.time()
                pty.tail(notice(offset=-age))
                self.assertFalse(pty.interrupt_confirmed.is_set())

    async def test_a_notice_cannot_confirm_two_interruptions(self):
        # The other side of the same hole: a record replayed by the tail after
        # it has already answered for one Esc must not answer for the next.
        pty = FakePty()
        first = notice()
        pty.interrupt_since = time.time() - 1
        pty.tail(first)
        self.assertTrue(pty.interrupt_confirmed.is_set())

        pty.interrupt_confirmed.clear()
        pty.interrupt_since = time.time() - 1
        pty.tail(first)

        self.assertFalse(
            pty.interrupt_confirmed.is_set(),
            "a spent notice may not confirm a second interruption",
        )
        self.assertIn(record_key(first), pty.interrupt_records_used)

    async def test_an_older_notice_arriving_late_does_not_confirm_this_esc(self):
        # The transcript tail can be behind. A notice from a *previous*
        # interruption may be read after this Esc; clearing an Event alone
        # would let it stand in for the one we are waiting for.
        pty = FakePty()

        async def replay_stale():
            await asyncio.sleep(0)
            pty.tail(notice(offset=-600))

        asyncio.create_task(replay_stale())
        confirmed = await antigravity_interrupt(pty, timeout=0.2, settle_timeout=1)

        self.assertFalse(confirmed)
        self.assertFalse(pty.interrupt_confirmed.is_set())

    async def test_a_notice_without_a_usable_timestamp_does_not_confirm(self):
        # Absent or unparsable: neither can be placed on either side of the
        # boundary, so neither may stand in for the record we asked for.
        for created_at in (None, "", "not a timestamp", "2026-13-45T99:99:99Z"):
            with self.subTest(created_at=created_at):
                self.assertFalse(is_interrupt_record(
                    {"source": "SYSTEM", "type": "ERROR_MESSAGE",
                     "created_at": created_at,
                     "content": "Error: The stream was interrupted."},
                    since=time.time(),
                ))

    async def test_confirmation_waits_for_the_turn_to_close_not_just_the_notice(self):
        # Antigravity accepts a mid-turn submission and silently drops it, so
        # the notice alone is not the boundary a message may be pasted into.
        pty = FakePty(turn_open=True)

        async def confirm():
            await asyncio.sleep(0)
            pty.tail(notice())

        asyncio.create_task(confirm())
        confirmed = await antigravity_interrupt(pty, timeout=1, settle_timeout=0.15)

        self.assertFalse(confirmed, "the turn never closed")

    async def test_a_turn_closing_after_the_notice_completes_the_confirmation(self):
        pty = FakePty(turn_open=True)

        async def confirm_then_close():
            await asyncio.sleep(0)
            pty.tail(notice())
            await asyncio.sleep(0.05)
            pty._turn_open = False

        asyncio.create_task(confirm_then_close())
        confirmed = await antigravity_interrupt(pty, timeout=1, settle_timeout=2)

        self.assertTrue(confirmed)

    async def test_a_keystroke_alone_is_not_a_confirmation(self):
        pty = FakePty()

        confirmed = await antigravity_interrupt(pty, timeout=0.05)

        self.assertFalse(confirmed)
        self.assertEqual(pty.written, [ESCAPE], "Esc was sent; only the receipt is missing")

    async def test_a_dead_process_is_not_typed_at(self):
        pty = FakePty(alive=False)

        self.assertFalse(await antigravity_interrupt(pty, timeout=0.05))
        self.assertEqual(pty.written, [])

    async def test_a_stale_confirmation_cannot_satisfy_the_next_interrupt(self):
        pty = FakePty()
        pty.interrupt_confirmed.set()

        confirmed = await antigravity_interrupt(pty, timeout=0.05)

        self.assertFalse(confirmed, "each interrupt waits for its own record")


if __name__ == "__main__":
    unittest.main()
