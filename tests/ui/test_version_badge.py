"""Browser coverage for what the version badge claims, and for unreadable frames.

The badge read `v0.21.1` against a `v0.21.3` server for hours and nothing was
wrong enough to notice: the version was fetched once at page load and never
again, while the reconnect after a Python-only restart correctly declined to
reload the unchanged bundle. Two separate facts — *what server am I connected
to* and *is my JavaScript current* — were being answered by one number.

These pin the three outcomes a hello can now have:

  - a same-build hello with a new version updates the badge **without reloading**;
  - a different-build hello reloads, even when the frame is otherwise unreadable,
    because that tab does not need an error — it needs the matching client;
  - a same-build hello missing a required field is a *contract* failure, and must
    not be reported as a network outage.

The last one matters most. `decodeWireEvent` throws, and before this the throw
escaped into `onmessage`, leaving `ready` false forever under a banner blaming
the network for a disagreement about the protocol.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402

LINES = ["alpha line"]

# Count documents, not history entries — a reload starts a fresh timeline, so
# `performance.getEntriesByType("navigation")` cannot see one.
COUNT_BOOTS = "sessionStorage.setItem('boots', String(Number(sessionStorage.getItem('boots') || 0) + 1));"

DELIVER = """
(frame) => {
  window.partyline.wire.socket.dispatchEvent(new MessageEvent("message", { data: frame }));
}
"""

# Teardown nulls `wire.socket`, so a post-incompatibility dispatch through the
# getter throws a TypeError and "proves" no state changed without ever reaching
# the stale handler. Hold the original socket so the generation guard is what
# actually gets exercised.
RETAIN_SOCKET = "() => { window.__socket = window.partyline.wire.socket; }"
DELIVER_RETAINED = """
(frame) => {
  window.__socket.dispatchEvent(new MessageEvent("message", { data: frame }));
}
"""


def open_line(ui):
    page = ui.page
    with page.expect_response(
        lambda response: "/api/conversations/" in response.url and response.request.method == "GET"
    ):
        page.locator(".conv-row .conv").first.click()
    page.wait_for_selector("#composer")
    page.wait_for_function("() => window.partyline.wire.ready")
    return page.evaluate("() => window.partyline.room.conversation.id")


def tab_build(page):
    """The build this document is running.

    Read from the badge's tooltip rather than a global: `__PARTYLINE_BUILD__`
    is a compile-time constant Vite substitutes, so it does not exist at
    runtime for a test to ask about. The tooltip is the only place the value is
    actually observable — which is the point of putting it there.
    """
    title = page.locator("#ver").get_attribute("title") or ""
    _, _, tail = title.partition("build ")
    return tail.strip() or None


def boots(page):
    return int(page.evaluate("() => sessionStorage.getItem('boots') || '0'"))


class VersionBadgeTest(unittest.TestCase):
    def test_a_new_version_on_the_same_build_updates_the_badge_without_reloading(self):
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            page.add_init_script(COUNT_BOOTS)
            page.reload()
            conversation_id = open_line(ui)
            build = tab_build(page)
            before = boots(page)

            page.evaluate(DELIVER, json.dumps({
                "type": "hello", "conversation_id": conversation_id,
                "handle": "operator", "build": build, "version": "9.9.9",
            }))

            page.wait_for_function("() => window.partyline.session.version === '9.9.9'", timeout=5000)
            page.wait_for_selector("#ver:text-is('v9.9.9')", timeout=5000)
            # The whole point: no hard refresh was needed to correct it.
            self.assertEqual(boots(page), before)

    def test_the_badge_says_which_build_this_tab_is_running(self):
        """`version` answers "what server"; the tooltip answers "what code".
        Keeping both visible is what makes a stale tab diagnosable by looking."""
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            open_line(ui)
            tooltip = page.locator("#ver").get_attribute("title")
            self.assertIn("server v", tooltip)
            self.assertTrue("build " in tooltip or "dev build" in tooltip, tooltip)

    def test_an_unreadable_same_build_hello_is_a_contract_failure_not_an_outage(self):
        """The control that matters. A required field the server omits used to
        throw out of `onmessage`, leaving the tab insisting the wire was down
        while the socket was perfectly healthy — blaming the network for a
        protocol disagreement."""
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            conversation_id = open_line(ui)
            build = tab_build(page)
            page.evaluate(RETAIN_SOCKET)

            # A hello with no `version`, on the build this tab is already running.
            page.evaluate(DELIVER, json.dumps({
                "type": "hello", "conversation_id": conversation_id,
                "handle": "operator", "build": build,
            }))
            page.wait_for_timeout(500)

            outage = page.evaluate("() => window.partyline.wire.outage")
            self.assertIsNotNone(outage, "an unreadable frame was silently ignored")
            # Names the disagreement, not a culprit: a same-build malformed
            # hello can equally be a server defect, and telling someone their
            # tab is stale sends them reloading into the same failure.
            self.assertIn("protocol mismatch", outage["message"])
            self.assertNotIn("wire is down", outage["message"])
            self.assertNotIn("out of date", outage["message"])

            # Terminal, not merely terminal-looking: a banner announcing the tab
            # is finished while the socket keeps dispatching is the same
            # says-one-thing-does-another failure this exercise is about.
            self.assertTrue(page.evaluate("() => window.partyline.wire.stopped"))
            self.assertIsNone(page.evaluate("() => window.partyline.wire.socket"),
                              "the incompatible socket was left attached")
            before = page.evaluate("() => window.partyline.session.version")
            page.evaluate(DELIVER_RETAINED, json.dumps({
                "type": "hello", "conversation_id": conversation_id,
                "handle": "operator", "build": build, "version": "7.7.7",
            }))
            page.wait_for_timeout(400)
            self.assertEqual(
                page.evaluate("() => window.partyline.session.version"), before,
                "a later valid frame mutated state after incompatibility")
            self.assertFalse(page.evaluate("() => window.partyline.wire.ready"))

    def test_an_unreadable_hello_from_a_different_build_reloads_instead(self):
        """A tab whose bundle is merely old should repair itself. Checking the
        build *before* declaring the frame unreadable is what makes that
        possible; the strict-parse-first version stranded exactly this case."""
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            page.add_init_script(COUNT_BOOTS)
            page.reload()
            conversation_id = open_line(ui)
            before = boots(page)

            # No `version`, and a build this tab is definitely not running.
            page.evaluate(DELIVER, json.dumps({
                "type": "hello", "conversation_id": conversation_id,
                "handle": "operator", "build": "0000000000000000",
            }))

            page.wait_for_function(
                f"() => Number(sessionStorage.getItem('boots') || 0) > {before}", timeout=8000
            )


if __name__ == "__main__":
    unittest.main()
