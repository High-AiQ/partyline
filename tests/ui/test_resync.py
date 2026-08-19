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

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402

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
    with page.expect_response(
        lambda response: "/api/conversations/" in response.url and response.request.method == "GET"
    ):
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

        `room.open()` has just fetched when the first hello arrives. Re-fetching
        there would double every line change, and — worse — would make the test
        above pass without a reconnect ever being distinguished from a connect,
        which is the entire behaviour under test.
        """
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            page.evaluate("() => { window.__detailFetches = 0; }")
            page.on(
                "response",
                lambda response: page.evaluate("() => { window.__detailFetches++; }")
                if "/api/conversations/" in response.url and response.request.method == "GET"
                else None,
            )

            open_first_line(ui)
            page.wait_for_timeout(1000)

            # Exactly the one fetch `open()` performs, with no handshake echo.
            self.assertEqual(page.evaluate("() => window.__detailFetches"), 1)

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
            page.request.post(
                f"{ui.base_url}/api/conversations/{conversation_id}/topic",
                data={"topic": "spoken during the outage"},
                headers=ui.auth_headers,
            )

            page.wait_for_function("() => window.partyline.wire.ready === true", timeout=15000)

            # Assert the property rather than a notice's wording: after catching
            # up, the tab must hold every message the server has.
            page.wait_for_function(
                """() => fetch(`/api/conversations/${window.partyline.room.conversation.id}`, {
                       headers: {Authorization: `Bearer ${localStorage.getItem('partyline_access_token')}`}
                     })
                     .then(r => r.json())
                     .then(d => {
                       const here = new Set(window.partyline.room.messages.map(m => m.id));
                       return d.messages.every(m => here.has(m.id));
                     })""",
                timeout=8000,
            )


if __name__ == "__main__":
    unittest.main()
