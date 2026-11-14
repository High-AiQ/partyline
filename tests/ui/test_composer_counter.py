"""The draft length counter appearing must not move the composer at any width."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import seed_room, ui_session  # noqa: E402

SELECTORS = ("#input", "#send", ".box")


class ComposerCounterTest(unittest.TestCase):
    def test_counter_appearing_moves_nothing_at_any_width(self):
        for width in (390, 900, 1000, 1050, 1280, 1400):
            with self.subTest(width=width), ui_session(
                ["Counter line"], viewport={"width": width, "height": 844}
            ) as ui:
                page = ui.page
                page.add_style_tag(content="#fenceUnavailable { display: none !important; }")
                page.get_by_text("Counter line").first.click()
                page.locator("#input").wait_for(state="visible")
                seed_room(page)
                boxes = {}
                for length in (990, 1010):
                    page.fill("#input", "a" * length)
                    page.wait_for_timeout(100)
                    boxes[length] = [page.locator(s).bounding_box() for s in SELECTORS]
                self.assertEqual(page.locator(".hint .count").inner_text(), "1,010 / 10,000")
                self.assertEqual(boxes[990], boxes[1010])


if __name__ == "__main__":
    unittest.main()
