"""Browser coverage for the composer caret.

The caret lives in the DOM, and the bug this guards was a reactive effect
re-running on every keystroke and slamming the caret to the end of the text —
a failure only a real browser, typing real key events into a real textarea,
can see. A unit test against the pure text helpers would pass either way.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import seed_room, ui_session  # noqa: E402


def caret(page) -> int:
    return page.evaluate("() => document.querySelector('#input').selectionStart")


def text(page) -> str:
    return page.evaluate("() => document.querySelector('#input').value")


class ComposerCaretTest(unittest.TestCase):
    def test_typing_mid_text_keeps_the_caret_where_it_was(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            page.locator(".conv-row .conv").first.click()
            page.locator("#input").wait_for(state="visible")

            box = page.locator("#input")
            box.click()
            page.keyboard.type("helloworld")
            for _ in range(5):
                page.keyboard.press("ArrowLeft")
            self.assertEqual(caret(page), 5)

            # Two keystrokes: with the bug the first one re-runs the
            # external-edit effect, the caret jumps to the end, and the second
            # letter lands there instead of after the first.
            page.keyboard.type("AB")
            self.assertEqual(text(page), "helloABworld")
            self.assertEqual(caret(page), 7)

    def test_a_board_mention_still_drops_the_caret_at_the_end(self):
        """Negative control: the effect exists for a reason.

        Clicking a jack's name appends its handle to the draft, and the caret
        must follow it to the end — that is the behavior the effect is for.
        """
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            is_detail = lambda response: (  # noqa: E731
                "/api/conversations/" in response.url and response.request.method == "GET")
            with page.expect_response(is_detail):
                page.locator(".conv-row .conv").first.click()
            page.locator("#input").wait_for(state="visible")
            seed_room(page)
            box = page.locator("#input")
            box.click()
            page.keyboard.type("hi")
            page.keyboard.press("ArrowLeft")

            page.locator(".jack .name").first.click()
            page.wait_for_timeout(100)

            self.assertEqual(text(page), "hi @sol ")
            self.assertEqual(caret(page), len("hi @sol "))


if __name__ == "__main__":
    unittest.main()
