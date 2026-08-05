"""Browser coverage for the stop-partyline lever.

Whether the server actually goes down, and whether the page then says so, is a
whole-system question: route, background task, broadcast, and client state all
have to line up. Only a real browser against a real server can answer it.
"""

import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402


def server_is_up(base_url):
    try:
        with urllib.request.urlopen(f"{base_url}/api/version", timeout=1):
            return True
    except (urllib.error.URLError, OSError):
        return False


class ShutdownTest(unittest.TestCase):
    def test_the_dialog_warns_before_anything_stops(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.click("#stopServer")
            modal = page.locator(".modal")
            modal.wait_for(state="visible")
            # The dialog fetches what is running before it can warn about it.
            modal.locator(".live-list").wait_for(state="visible")

            self.assertIn("every line", modal.inner_text())
            # Nothing has happened yet: cancelling must leave the server alone.
            modal.get_by_text("cancel", exact=True).click()
            page.wait_for_timeout(500)
            self.assertTrue(server_is_up(ui.base_url))

    def test_stopping_takes_the_server_down_and_the_page_says_so(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.wait_for_timeout(400)

            page.click("#stopServer")
            page.locator(".modal .live-list").wait_for(state="visible")
            page.locator(".modal button.danger").click()

            # The page reports a deliberate stop, not a reconnect it will retry.
            page.locator("#wireDown.stopped").wait_for(state="visible", timeout=10000)
            self.assertIn("stopped", page.locator("#wireDown").inner_text())
            page.wait_for_timeout(1500)
            self.assertFalse(server_is_up(ui.base_url), "the server is still listening")
