"""Browser coverage for the reattach offer's two-sided behaviour.

The offer is a protocol, not a panel. It arrives unprompted over the socket
after a restart, it is scoped to one line, and answering it has to put an exact
token back on the wire. Asserting that the markup renders would leave the two
halves that can actually be wrong — who is allowed to see it, and what leaves
the browser — completely uncovered.

The events are delivered as real frames through the page's own socket, so the
Zod decoder, the discriminated union and the line check all run for real.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402

LINES = ["alpha line", "beta line"]

# Record every frame the page sends, so a decision can be asserted on the wire
# rather than on a store the page also owns.
SPY_ON_SENDS = """
() => {
  window.__sent = [];
  const socket = window.partyline.wire.socket;
  const send = socket.send.bind(socket);
  socket.send = (data) => { window.__sent.push(data); return send(data); };
}
"""

DELIVER = """
(event) => {
  window.partyline.wire.socket.dispatchEvent(
    new MessageEvent("message", { data: JSON.stringify(event) }),
  );
}
"""


def offer_for(conversation_id, token="offer-token-1"):
    return {
        "type": "reattach_offer",
        "conversation_id": conversation_id,
        "token": token,
        "attachments": [
            {"id": "att-1", "name": "sol", "adapter": "claude"},
            {"id": "att-2", "name": "terra", "adapter": "claude"},
        ],
        "debrief": "pull, re-read your slice, and post status.",
    }


def open_first_line(ui):
    page = ui.page
    with page.expect_response(
        lambda response: "/api/conversations/" in response.url and response.request.method == "GET"
    ):
        page.locator(".conv-row .conv").first.click()
    page.wait_for_selector("#composer")
    page.wait_for_function("() => window.partyline.wire.ready")
    return page.evaluate("() => window.partyline.room.conversation.id")


def decisions(page):
    """Every reattach command the page actually put on the wire."""
    frames = [json.loads(frame) for frame in page.evaluate("() => window.__sent")]
    return [frame for frame in frames if frame.get("type") == "reattach"]


class ReattachOfferTest(unittest.TestCase):
    def test_an_offer_for_this_line_is_shown_and_answered_on_the_wire(self):
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            conversation_id = open_first_line(ui)
            page.evaluate(SPY_ON_SENDS)

            page.evaluate(DELIVER, offer_for(conversation_id))
            modal = page.locator(".modal")
            modal.wait_for(state="visible", timeout=5000)
            self.assertIn("@sol", modal.inner_text())
            self.assertIn("@terra", modal.inner_text())
            self.assertIn("post status", modal.inner_text())

            modal.get_by_text("not now", exact=True).click()

            page.wait_for_function("() => window.__sent.some(f => f.includes('reattach'))", timeout=5000)
            sent = decisions(page)
            self.assertEqual(len(sent), 1, sent)
            self.assertEqual(sent[0]["token"], "offer-token-1")
            self.assertEqual(sent[0]["action"], "cancel")

    def test_an_offer_for_another_line_is_not_shown(self):
        """The control. Without it the test above would pass just as happily if
        the dialog appeared for every offer on the server, which is exactly the
        authorization bug worth catching: a plan is scoped to the line that
        asked for it, and a tab on a different line has no business answering."""
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            open_first_line(ui)
            page.evaluate(SPY_ON_SENDS)

            # The room is mutated synchronously by the frame handler, so this
            # can be asserted immediately. A sleep here would make "the modal
            # had not appeared yet" a passing condition, which is the thing a
            # control is supposed to rule out.
            page.evaluate(DELIVER, offer_for("some-other-line-entirely"))
            self.assertIsNone(page.evaluate("() => window.partyline.room.reattachOffer"))
            self.assertEqual(page.locator(".modal").count(), 0)
            self.assertEqual(decisions(page), [])

    def test_a_decision_from_another_tab_dismisses_the_offer_here(self):
        """The server broadcasts the decision, and that is what clears the
        offer — in every tab, including ones nobody touched."""
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            conversation_id = open_first_line(ui)

            page.evaluate(DELIVER, offer_for(conversation_id))
            page.locator(".modal").wait_for(state="visible", timeout=5000)

            page.evaluate(DELIVER, {
                "type": "reattach_decision",
                "conversation_id": conversation_id,
                "token": "offer-token-1",
                "action": "started",
            })

            page.locator(".modal").wait_for(state="detached", timeout=5000)
            self.assertIsNone(page.evaluate("() => window.partyline.room.reattachOffer"))

    def test_a_decision_for_a_different_offer_leaves_this_one_up(self):
        """Control for the dismissal above: matching on the line alone would
        let a stale token's decision close an offer it has nothing to do with."""
        with ui_session(LINES, handle="operator") as ui:
            page = ui.page
            conversation_id = open_first_line(ui)

            page.evaluate(DELIVER, offer_for(conversation_id))
            page.locator(".modal").wait_for(state="visible", timeout=5000)

            page.evaluate(DELIVER, {
                "type": "reattach_decision",
                "conversation_id": conversation_id,
                "token": "a-different-token",
                "action": "started",
            })

            self.assertIsNotNone(page.evaluate("() => window.partyline.room.reattachOffer"))
            self.assertTrue(page.locator(".modal").is_visible())


if __name__ == "__main__":
    unittest.main()
