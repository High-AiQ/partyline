"""Browser coverage for catching up after the wire comes back.

Events only reach a connected socket, so an outage is a hole in the tab's
knowledge that nothing else fills: `room.open()` is the only other thing that
fetches, and it runs on line changes, not on recovery. A server restart lands
squarely in that hole — it rewrites every attachment status with no sockets to
tell.

This was not theoretical. After a restart whose bundle happened not to change,
a running process showed as dead in the operator's tab until a manual refresh.
The build-id reload had been hiding the gap: every earlier restart changed the
bundle, so tabs reloaded and re-fetched by accident rather than by design.
"""

import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402

# Exactly the line-detail fetch: `/lead` and other conversation sub-resources
# also live under /api/conversations/ and must not be counted as detail reads.
DETAIL_FETCH = re.compile(r"/api/conversations/[0-9a-f-]{36}$")


def is_detail(response):
    return response.request.method == "GET" and bool(DETAIL_FETCH.fullmatch(urlparse(response.url).path))


LINES = ["alpha line", "beta line"]

# Rewrite what the tab believes, behind its back. A reconnect must correct this
# from the server; nothing else in the app will.
CORRUPT_ATTACHMENTS = """
() => {
  window.partyline.room.attachments = [{
    id: "ghost", name: "ghost", adapter: "raw", command: ["x"], cwd: "/tmp",
    status: "exited", created_at: 1,
  }];
}
"""

DROP_SOCKET = "() => { window.partyline.wire.socket.close(); }"


def open_first_line(ui):
    page = ui.page
    with page.expect_response(is_detail):
        page.locator(".conv-row .conv").first.click()
    page.wait_for_selector("#composer")
    page.wait_for_function("() => window.partyline.wire.ready")


def attachment_names(page):
    return page.evaluate("() => window.partyline.room.attachments.map(a => a.name)")


class ResyncTest(unittest.TestCase):
    def test_a_reconnect_replaces_state_the_tab_missed(self):
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            open_first_line(ui)

            page.evaluate(CORRUPT_ATTACHMENTS)
            self.assertEqual(attachment_names(page), ["ghost"])

            page.evaluate(DROP_SOCKET)
            page.wait_for_function("() => window.partyline.wire.ready === false", timeout=5000)
            page.wait_for_function("() => window.partyline.wire.ready === true", timeout=15000)

            # The server has no `ghost`; the reconnect must have gone and asked.
            page.wait_for_function(
                "() => !window.partyline.room.attachments.some(a => a.name === 'ghost')",
                timeout=5000,
            )

    def test_the_first_handshake_does_not_refetch(self):
        """The control, and the reason this is not simply "fetch on every hello".

        `room.open()` fetches a fast snapshot, then enriches attachment Git
        metadata separately. Repeating either on hello would double every line
        change, and — worse — would make the test above pass without a reconnect
        ever being distinguished from a connect,
        which is the entire behaviour under test.
        """
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            detail_fetches = []

            def remember_detail(response):
                if is_detail(response):
                    detail_fetches.append(urlparse(response.url).query)

            # Never re-enter Playwright's sync API from a response callback:
            # nested page.evaluate can re-enter Waiter listener cleanup.
            page.on("response", remember_detail)

            open_first_line(ui)
            page.wait_for_timeout(1000)

            page.remove_listener("response", remember_detail)
            # Exactly one primary snapshot and one Git enrichment, no hello echo.
            self.assertCountEqual(detail_fetches, ["include_git=false", ""])

    def test_a_restart_request_filed_during_an_outage_shows_its_banner_on_reconnect(self):
        """The banner is event-carried state, exactly like attachment status.

        Filed while this tab is deaf, the restart_request frame reaches no
        socket; the reconnect must re-read the pending request or the banner
        stays hidden until a manual refresh — the person sees the ☏ notice in
        the caught-up feed with nothing to act on.
        """
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            open_first_line(ui)
            conversation_id = page.evaluate("() => window.partyline.room.conversation.id")

            page.evaluate(DROP_SOCKET)
            page.wait_for_function("() => window.partyline.wire.ready === false", timeout=5000)

            filed = page.request.post(
                f"{ui.base_url}/api/conversations/{conversation_id}/restart-request",
                data={"reason": "new build", "confirm_no_deploy": True},
                headers=ui.auth_headers,
            )
            self.assertTrue(filed.ok, filed.text())

            page.wait_for_function("() => window.partyline.wire.ready === true", timeout=15000)
            page.locator("#restartRequest").wait_for(state="visible", timeout=5000)
            self.assertIn(
                "asks to restart partyline", page.locator("#restartRequest").inner_text())

    def test_messages_missed_during_an_outage_arrive_on_reconnect(self):
        """An outage swallows message events too, and the feed must not keep the
        hole. `#absorb` dedupes by id, so re-fetching cannot double anything."""
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            open_first_line(ui)
            conversation_id = page.evaluate("() => window.partyline.room.conversation.id")

            page.evaluate(DROP_SOCKET)
            page.wait_for_function("() => window.partyline.wire.ready === false", timeout=5000)

            # Said while this tab was deaf, through a channel it is not watching.
            spoken = page.request.put(
                f"{ui.base_url}/api/conversations/{conversation_id}/topic",
                data={"topic": "spoken during the outage"},
                headers=ui.auth_headers,
            )
            self.assertTrue(spoken.ok, spoken.text())

            detail = page.request.get(
                f"{ui.base_url}/api/conversations/{conversation_id}", headers=ui.auth_headers
            ).json()
            self.assertTrue(any("spoken during the outage" in m["body"] for m in detail["messages"]))
            expected_ids = [message["id"] for message in detail["messages"]]

            page.wait_for_function("() => window.partyline.wire.ready === true", timeout=15000)

            # Assert the property rather than a notice's wording: after catching
            # up, the tab must hold every message the server has.
            page.wait_for_function(
                """ids => {
                  const here = new Set(window.partyline.room.messages.map(m => m.id));
                  return ids.every(id => here.has(id));
                }""",
                arg=expected_ids,
                timeout=8000,
            )


if __name__ == "__main__":
    unittest.main()
