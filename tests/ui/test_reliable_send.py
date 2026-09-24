"""Browser coverage for REST-first chat send."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402


class ReliableSendTest(unittest.TestCase):
    def test_a_swallowed_socket_send_still_lands_the_message(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.locator("#input").wait_for(state="visible")
            page.wait_for_timeout(500)

            page.evaluate(
                """() => {
                  const socket = window.partyline.wire.socket;
                  if (!socket) throw new Error('no socket');
                  socket.send = () => undefined;
                }"""
            )
            page.locator("#input").fill("survived the nap")
            page.locator("#send").click()
            page.get_by_text("survived the nap").wait_for(state="visible", timeout=10000)
            self.assertEqual(page.locator("#input").input_value(), "")

    def test_a_failed_rest_post_keeps_the_draft_and_shows_a_notice(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.locator("#input").wait_for(state="visible")
            page.wait_for_timeout(500)

            def fail_post(route):
                if route.request.method == "POST":
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"could not send message"}',
                    )
                else:
                    route.continue_()

            page.route("**/api/conversations/*/messages", fail_post)
            page.locator("#input").fill("held back")
            page.locator("#send").click()
            page.locator("#wireNotice").wait_for(state="visible", timeout=10000)
            self.assertEqual(page.locator("#input").input_value(), "held back")
            self.assertIn("could not send message", page.locator("#wireNotice").inner_text())

    def test_wake_verify_replaces_a_socket_after_sleep(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(500)
            first = page.evaluate("() => window.partyline.wire.socket")

            page.evaluate("() => window.partyline.wire.noteHidden()")
            page.wait_for_timeout(1100)
            page.evaluate("() => window.partyline.wire.verifyOnWake()")
            page.wait_for_function(
                "(socket) => window.partyline.wire.socket && window.partyline.wire.socket !== socket",
                arg=first,
                timeout=10000,
            )


if __name__ == "__main__":
    unittest.main()
