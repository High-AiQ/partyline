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
            page.evaluate("() => { window.__partylineReloadControl = true; }")
            page.evaluate("() => window.partyline.wire.socket.close()")
            page.wait_for_timeout(2500)

            self.assertEqual(page.locator("#wireDown").count(), 0)
            self.assertTrue(page.evaluate("() => window.partyline.wire.ready"))
            self.assertTrue(page.evaluate("() => window.__partylineReloadControl"))

    def test_a_new_frontend_build_reloads_and_restores_the_draft(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.locator("#input").wait_for(state="visible")
            page.locator("#input").fill("keep this unfinished thought")
            route = page.url.split("#", 1)[1]
            build = page.evaluate(
                "() => fetch('/api/version').then(response => response.json()).then(x => x.build)"
            )
            other_build = ("0" if build[0] != "0" else "1") + build[1:]

            page.evaluate(
                """([build]) => {
                  window.__partylineReloadControl = true;
                  const conversation_id = window.partyline.room.conversation.id;
                  const handle = window.partyline.session.handle;
                  window.partyline.wire.socket.dispatchEvent(new MessageEvent('message', {
                    data: JSON.stringify({type: 'hello', conversation_id, handle, build}),
                  }));
                }""",
                [other_build],
            )

            page.wait_for_function(
                "() => window.__partylineReloadControl !== true", timeout=10000)
            page.locator("#input").wait_for(state="visible", timeout=10000)
            self.assertEqual(page.url.split("#", 1)[1], route)
            self.assertEqual(page.locator("#input").input_value(), "keep this unfinished thought")

    def test_a_shutdown_event_waits_then_reconnects_without_reloading(self):
        """A deliberate stop stays honest while still noticing the restart."""
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(500)

            # Deliver the event the shutdown route will broadcast.
            page.evaluate("() => { window.__partylineReloadControl = true; }")
            page.evaluate(
                "() => window.partyline.wire.socket.dispatchEvent(new MessageEvent('message',"
                " {data: JSON.stringify({type: 'shutdown'})}))")

            page.locator("#wireDown.stopped").wait_for(state="visible", timeout=5000)
            self.assertIn("waiting for a restart", page.locator("#wireDown").inner_text())

            # The harness server is still alive, standing in for a completed
            # restart. The retry should reconnect without reloading because its
            # build id is unchanged.
            page.wait_for_function("() => window.partyline.wire.ready", timeout=5000)
            page.locator("#wireDown").wait_for(state="detached", timeout=5000)
            self.assertTrue(page.evaluate("() => window.__partylineReloadControl"))


if __name__ == "__main__":
    unittest.main()
