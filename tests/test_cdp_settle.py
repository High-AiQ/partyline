"""Quiet/deadline waits are driven by fake one-shot timers, never wall time."""
import asyncio
from unittest import IsolatedAsyncioTestCase

from partyline_helper.cdp_actions import act
from partyline_helper.cdp_settle import Quiet
from partyline_helper.cdp_recipes import STATE
from tests.cdp_fakes import Fixture
from tests.screen_helper_fakes import checkpoint


class Clock:
    def __init__(self):
        self.now, self.timers = 0, []

    def __call__(self):
        return self.now

    def call_later(self, delay, callback, *args):
        class Timer:
            cancelled = False
            def cancel(self):
                self.cancelled = True
        timer = Timer()
        self.timers.append((self.now + delay, timer, callback, args))
        return timer

    def advance(self, delta):
        self.now += delta
        for deadline, timer, callback, args in sorted(self.timers, key=lambda t: t[0]):
            if not timer.cancelled and deadline <= self.now:
                timer.cancel()
                callback(*args)


class SettleTests(IsolatedAsyncioTestCase):
    async def test_event_resets_quiet_timer_and_deadline_is_absolute(self):
        clock = Clock()
        quiet = Quiet(clock, clock)
        task = asyncio.create_task(quiet.wait())
        await checkpoint()
        clock.advance(0.09)
        quiet.changed()
        clock.advance(0.02)
        self.assertFalse(task.done())
        clock.advance(0.09)
        self.assertEqual(await task, "quiet")
        self.assertFalse(quiet.waiters)
        task = asyncio.create_task(quiet.wait())
        await checkpoint()
        for _ in range(21):
            quiet.changed()
            clock.advance(0.099)
        self.assertEqual(await task, "deadline")
        self.assertTrue(all(timer.cancelled for _, timer, _, _ in clock.timers))

    async def test_event_during_post_action_read_reports_changing(self):
        fixture = Fixture()
        self.addAsyncCleanup(fixture.close)
        result = await fixture.read()
        page = await fixture.chrome.page(fixture.access)
        after_quiet = False
        async def quiet():
            nonlocal after_quiet
            after_quiet = True
            return "quiet"
        page.quiet.wait = quiet
        node = next(i["id"] for i in result["elements"] if i["control_type"] == "ComboBox")
        def hook(m):
            if (after_quiet and m["method"] == "Runtime.callFunctionOn"
                    and m["params"]["functionDeclaration"] == STATE):
                fixture.socket.event()
        fixture.socket.hook = hook
        result = await act(page, dict(element_id=node, action="select", value="New"))
        self.assertEqual(result["settle"], "changing")

    async def test_cancelling_wait_cancels_both_timers(self):
        clock = Clock()
        quiet = Quiet(clock, clock)
        task = asyncio.create_task(quiet.wait())
        await checkpoint()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(timer.cancelled for _, timer, _, _ in clock.timers))
