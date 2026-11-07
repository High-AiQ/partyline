"""The composer's icon controls and their floating notes stay inside a phone."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import seed_room, ui_session  # noqa: E402

PRESETS = {"default": "asr", "presets": [{"name": "asr", "kind": "command", "available": True}]}
DENY_MIC = """() => {
  navigator.mediaDevices.getUserMedia = () =>
    Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
}"""
LONG_NOTE = "a very long spoken sentence that keeps going " * 6


class ComposerIconsTest(unittest.TestCase):
    def test_controls_and_a_long_hands_free_note_fit_a_375px_phone(self):
        with ui_session(["Phone line"], viewport={"width": 375, "height": 812}) as ui:
            page = ui.page
            page.add_style_tag(content="#fenceUnavailable { display: none !important; }")
            page.route("**/api/transcribe/presets", lambda route: route.fulfill(json=PRESETS))
            page.get_by_text("Phone line").first.click()
            page.locator("#input").wait_for(state="visible")
            seed_room(page)
            self.assertEqual(page.locator("[data-composer-controls]").count(), 0)
            page.evaluate(DENY_MIC)
            page.locator("button.hands-free").click()
            bubble = page.locator("[data-composer-bubble]")
            bubble.wait_for(state="visible")
            page.evaluate(
                "(text) => { document.querySelector('[data-composer-bubble]').textContent = text; }",
                LONG_NOTE,
            )
            box = bubble.bounding_box()
            self.assertGreaterEqual(box["x"], 0)
            self.assertLessEqual(box["x"] + box["width"], 375)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            self.assertEqual(overflow, 0)


if __name__ == "__main__":
    unittest.main()
