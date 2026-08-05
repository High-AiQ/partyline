"""Browser coverage for what the page shows when the server goes away.

A dropped server, a scheduled restart and a slow network all arrive at the page
as the same event — a closed socket. Only a browser holding a real socket can
tell us what the user ends up looking at.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402


class WireStateTest(unittest.TestCase):
    def test_nothing_is_shown_while_the_wire_is_healthy(self):
        with ui_session(["alpha line"]) as ui:
            ui.page.locator(".conv-row .conv").first.click()
            ui.page.wait_for_timeout(800)
            self.assertEqual(ui.page.locator("#wireDown").count(), 0)

    def test_a_dead_server_is_reported_rather_than_silently_retried(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(500)

            ui.stop_server()

            # A 3s grace period before we say anything, so a quick reconnect
            # stays quiet; a genuinely dead server lands well inside 15s.
            page.locator("#wireDown").wait_for(state="visible", timeout=15000)
            self.assertIn("wire is down", page.locator("#wireDown").inner_text())

    def test_a_single_drop_does_not_flash_a_banner(self):
        """Negative control: reconnecting cleanly must stay quiet.

        The retry lands at ~1.5s, inside the 3s grace period, so the banner must
        never appear. If this starts failing, the grace period has been lost and
        every page reload will look like an outage.
        """
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(500)

            # Drop the socket once from the client side; the server is still up,
            # so the retry succeeds and nothing should ever appear.
            page.evaluate("() => window.partyline.wire.socket.close()")
            page.wait_for_timeout(2500)

            self.assertEqual(page.locator("#wireDown").count(), 0)
            self.assertTrue(page.evaluate("() => window.partyline.wire.ready"))

    def test_a_shutdown_event_says_it_is_not_coming_back(self):
        """The distinction that makes this worth having: a crash is
        'reconnecting', a deliberate stop is 'it has stopped'."""
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(500)

            # Deliver the event the shutdown route will broadcast.
            page.evaluate(
                "() => window.partyline.wire.socket.dispatchEvent(new MessageEvent('message',"
                " {data: JSON.stringify({type: 'shutdown'})}))")

            page.locator("#wireDown.stopped").wait_for(state="visible", timeout=5000)
            self.assertIn("stopped", page.locator("#wireDown").inner_text())
            # And it must stop claiming a reconnect is on the way.
            page.wait_for_timeout(2000)
            self.assertNotIn("reconnecting", page.locator("#wireDown").inner_text())


if __name__ == "__main__":
    unittest.main()
