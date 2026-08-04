"""Browser coverage for per-line handle claims.

The handshake is a two-sided protocol between the page and the server, and its
sharpest case — a browser reconnecting onto a socket the server still believes
is live — cannot be reproduced without a real browser holding a real socket.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402

LINES = ["alpha line", "beta line"]


def sign_in(page, handle, base_url, line_index=0):
    """Take a fresh page through the gate and onto a line."""
    page.goto(base_url)
    page.wait_for_selector("#gateName")
    page.fill("#gateName", handle)
    page.click("#gateForm button[type=submit]")
    page.wait_for_selector(".conv-row")
    page.locator(".conv-row .conv").nth(line_index).click()
    return page


def say(page, text):
    """Type a message and send it, returning nothing — assert on the feed."""
    box = page.locator("#composer textarea, #composer input[type=text]").first
    box.fill(text)
    box.press("Enter")


class HandleClaimTest(unittest.TestCase):
    def test_two_browsers_cannot_hold_one_handle_on_a_line(self):
        with ui_session(LINES, handle="first") as ui:
            first = ui.page
            first.locator(".conv-row .conv").first.click()
            first.wait_for_function("() => window.__handshaken !== false")

            # A second, entirely separate browser context: its own storage, so
            # its own client id. Same handle, same line.
            context = first.context.browser.new_context(viewport={"width": 1280, "height": 800})
            second = context.new_page()
            try:
                sign_in(second, "first", ui.base_url)
                second.wait_for_selector("#gate", state="visible", timeout=10000)
                gate = second.locator("#gate").inner_text()
                self.assertIn("taken", gate.lower(), gate)
            finally:
                context.close()

    def test_the_same_handle_is_free_on_a_different_line(self):
        """A claim is per line, so the same person can be `first` in both."""
        with ui_session(LINES, handle="first") as ui:
            ui.page.locator(".conv-row .conv").first.click()

            context = ui.page.context.browser.new_context(viewport={"width": 1280, "height": 800})
            second = context.new_page()
            try:
                sign_in(second, "first", ui.base_url, line_index=1)
                # No gate means the claim was granted on the second line.
                second.wait_for_timeout(1500)
                self.assertFalse(second.locator("#gate").is_visible())
            finally:
                context.close()

    def test_reloading_keeps_you_signed_in_on_your_own_handle(self):
        """A reload closes the socket cleanly, so the claim is simply released
        and retaken. This is the common path, and it must not bounce anyone to
        the gate — but note it does *not* exercise `client_id`, because there is
        no stale claim to supersede. The half-open case is covered by
        `test_matching_client_id_reclaims_a_stale_handle` in tests/test_server.py,
        which can plant a stale claim; a browser cannot fake one.
        """
        with ui_session(LINES, handle="first") as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(500)

            page.reload()
            page.wait_for_selector(".conv-row")
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(1500)

            self.assertFalse(page.locator("#gate").is_visible(),
                             "the gate reappeared: the browser lost its own handle on reload")

    def test_a_shared_client_id_takes_the_handle_from_a_live_socket(self):
        """Takeover with the superseded socket genuinely still open.

        This is the browser-reachable half of the `client_id` rule, and the
        exact counterpart of the two-browser rejection above: same handle, same
        line, live incumbent — granted here only because the client ids match.
        """
        with ui_session(LINES, handle="first") as ui:
            incumbent = ui.page
            incumbent.locator(".conv-row .conv").first.click()
            incumbent.wait_for_timeout(500)
            client_id = incumbent.evaluate("() => localStorage.getItem('partyline_client_id')")
            self.assertTrue(client_id, "the page never minted a client id")

            context = incumbent.context.browser.new_context(viewport={"width": 1280, "height": 800})
            second = context.new_page()
            try:
                second.goto(ui.base_url)
                second.evaluate(
                    "id => { localStorage.setItem('partyline_client_id', id);"
                    " localStorage.setItem('partyline_user', 'first'); }", client_id)
                second.reload()
                second.wait_for_selector(".conv-row")
                second.locator(".conv-row .conv").first.click()
                second.wait_for_timeout(1500)

                self.assertFalse(second.locator("#gate").is_visible(),
                                 "the same browser identity was refused its own handle")
            finally:
                context.close()

    def test_a_human_cannot_take_a_running_process_handle(self):
        with ui_session(LINES, handle="first") as ui:
            conv_id = ui.page.evaluate("() => state.convs[0].id")
            ui.page.request.post(
                f"{ui.base_url}/api/conversations/{conv_id}/attachments",
                data={"name": "worker", "adapter": "raw", "command": "sleep 60", "cwd": "/tmp"})

            context = ui.page.context.browser.new_context(viewport={"width": 1280, "height": 800})
            second = context.new_page()
            try:
                sign_in(second, "worker", ui.base_url)
                second.wait_for_selector("#gate", state="visible", timeout=10000)
                self.assertIn("process", second.locator("#gate").inner_text().lower())
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
