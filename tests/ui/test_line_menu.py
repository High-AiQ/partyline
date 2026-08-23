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

    def test_close_processes_item_opens_the_bulk_detach_modal(self):
        with ui_session(["alpha line"]) as ui:
            menu = ui.open_row_menu()
            menu.get_by_text("close processes", exact=True).click()

            modal = ui.page.locator(".modal")
            modal.wait_for(state="visible")
            modal.get_by_text("The line and its history stay", exact=False).wait_for()
            self.assertIn("close processes · alpha line", modal.text_content())
            self.assertIn("The line and its history stay", modal.text_content())

    def test_menu_closes_on_an_outside_click(self):
        """`hidden` alone is not enough: an author `display` rule outranks the
        UA stylesheet's `[hidden]{display:none}`, so the menu stayed on screen
        even though closeLineMenu() had already released it.
        """
        with ui_session(["alpha line", "beta line"]) as ui:
            page = ui.page
            menu = ui.open_row_menu()
            self.assertTrue(menu.is_visible())

            page.mouse.click(640, 400)

            page.locator(".conv-menu").wait_for(state="hidden", timeout=5000)
            self.assertEqual(page.locator(".conv-menu").count(), 0)

    def test_menu_closes_on_escape(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            ui.open_row_menu()
            page.keyboard.press("Escape")
            page.locator(".conv-menu").wait_for(state="hidden", timeout=5000)

    def test_choosing_an_item_closes_the_menu(self):
        with ui_session(["alpha line"]) as ui:
            page = ui.page
            menu = ui.open_row_menu()
            menu.get_by_text("rename", exact=True).click()
            page.locator(".conv-menu").wait_for(state="hidden", timeout=5000)

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
