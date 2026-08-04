"""Browser regressions for the line actions menu.

Run explicitly: ``uv run python -m unittest tests/ui/test_line_menu.py``.
These tests deliberately live outside the coverage-discovery package: browser
checks complement the deterministic unit suite and should not affect its gate.
"""

import unittest

from scripts.uishot import ui_session


class LineMenuTest(unittest.TestCase):
    def test_menu_survives_pointer_trip_and_opens_rename_modal(self):
        with ui_session(["alpha line", "beta line"]) as ui:
            page = ui.page
            selected_name = page.locator(".conv-row").first.locator(".conv").text_content()
            menu = ui.open_row_menu()

            box = menu.bounding_box()
            self.assertIsNotNone(box)
            page.mouse.move(box["x"] + 12, box["y"] + 12)
            menu.get_by_text("rename", exact=True).click()

            modal = page.locator(".modal")
            modal.wait_for(state="visible")
            self.assertIn(f"rename line · {selected_name}", modal.text_content())

    def test_menu_surface_is_opaque_and_lifted_above_rail(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            ui.open_row_menu()

            menu_background, rail_background = page.evaluate("""() => [
                getComputedStyle(document.querySelector('.conv-menu')).backgroundColor,
                getComputedStyle(document.querySelector('#rail')).backgroundColor,
            ]""")
            self.assertNotEqual(menu_background, rail_background)
            self.assertNotIn("rgba", menu_background)
            self.assertNotIn("transparent", menu_background)

    def test_last_row_menu_stays_inside_viewport(self):
        with ui_session([f"line {number}" for number in range(40)]) as ui:
            page = ui.page
            menu = ui.open_row_menu(-1)

            box = menu.bounding_box()
            viewport = page.evaluate("() => ({width: innerWidth, height: innerHeight})")
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box["x"], 0)
            self.assertGreaterEqual(box["y"], 0)
            self.assertLessEqual(box["x"] + box["width"], viewport["width"])
            self.assertLessEqual(box["y"] + box["height"], viewport["height"])
