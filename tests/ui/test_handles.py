"""Browser coverage for authenticated identity across concurrent tabs.

This genuinely needs a browser: localStorage carries the shared login while
sessionStorage keeps each tab's reconnect identity distinct, and a handle
change closes both live sockets before they come back under the new name.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402


def open_line(page):
    page.wait_for_selector(".conv-row")
    page.locator(".conv-row .conv").first.click()
    page.wait_for_function("() => window.partyline.wire.ready")


class AuthenticatedHandleTest(unittest.TestCase):
    def test_two_tabs_share_an_account_without_superseding_each_other(self):
        with ui_session(["alpha line"], handle="first") as ui:
            first = ui.page
            open_line(first)
            second = first.context.new_page()
            try:
                second.goto(ui.base_url)
                open_line(second)

                first_id = first.evaluate(
                    "() => sessionStorage.getItem('partyline_client_id')")
                second_id = second.evaluate(
                    "() => sessionStorage.getItem('partyline_client_id')")
                self.assertTrue(first_id)
                self.assertTrue(second_id)
                self.assertNotEqual(first_id, second_id)
                # Let the old shared-client-id takeover loop show itself; a
                # transient overlap immediately after hello is not evidence.
                second.wait_for_timeout(750)
                self.assertTrue(first.evaluate("() => window.partyline.wire.ready"))
                self.assertTrue(second.evaluate("() => window.partyline.wire.ready"))
            finally:
                second.close()

    def test_cross_tab_login_starts_the_protected_app_without_a_reload(self):
        with ui_session(["alpha line"], handle="first") as ui:
            first = ui.page
            second = first.context.new_page()
            try:
                second.goto(ui.base_url)
                second.wait_for_selector("#convs")

                first.get_by_role("button", name="logout").click()
                for page in (first, second):
                    page.wait_for_selector("#authForm")

                email, password = ui.auth_credentials
                first.locator("#authEmail").fill(email)
                first.locator("#authPassword").fill(password)
                first.locator("#authForm").evaluate("form => form.requestSubmit()")

                # The second tab receives only storage events. Seeing the rail
                # proves its signed-in rising edge ran the full connect path.
                second.wait_for_selector(".conv-row")
                self.assertEqual(second.locator(".account .handle").inner_text(), "@first")
            finally:
                second.close()

    def test_handle_change_reconnects_every_tab_under_the_new_name(self):
        with ui_session(["alpha line"], handle="first") as ui:
            first = ui.page
            open_line(first)
            second = first.context.new_page()
            refreshes = []
            try:
                second.goto(ui.base_url)
                open_line(second)
                for page in (first, second):
                    page.on("request", lambda request: (
                        refreshes.append(request.url)
                        if request.url.endswith("/api/auth/refresh") else None))

                first.locator(".account .handle").click()
                first.locator("#newHandle").fill("renamed")
                first.locator(".line-actions .primary").click()
                for page in (first, second):
                    page.wait_for_function(
                        "() => window.partyline.session.handle === 'renamed'"
                        " && window.partyline.wire.ready")

                second.evaluate("() => window.partyline.room.say('after rename')")
                first.wait_for_function(
                    "() => window.partyline.room.messages.some("
                    "message => message.body === 'after rename' && message.sender === 'renamed')")
                self.assertEqual(refreshes, [])
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
