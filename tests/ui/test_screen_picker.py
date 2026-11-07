"""The selection overlay tracks the preview pixels used for desktop mapping."""
import base64
import io
import unittest

from PIL import Image

from scripts.uishot import ui_session


class ScreenPickerTest(unittest.TestCase):
    def test_selection_outline_matches_dragged_preview_area(self):
        data = io.BytesIO()
        Image.new("RGB", (320, 180), (80, 110, 125)).save(data, format="PNG")
        preview = base64.b64encode(data.getvalue()).decode("ascii")
        with ui_session(["Screen line"]) as ui:
            page = ui.page
            page.locator(".conv-row").first.click()
            # The browser harness runs nested in the development fence, where
            # its preflight warning can cover the controls under test.
            page.add_style_tag(content="#fenceUnavailable { display: none !important; }")
            page.route("**/api/screen/devices?*", lambda route: route.fulfill(json={"devices": [{
                "id": "d", "name": "Desk", "os": "test", "online": True,
                "monitors": [{"id": 1, "x": -1600, "y": 0, "width": 1600,
                              "height": 900, "scale": 1, "primary": True}],
            }]}))
            page.route("**/api/screen/preview?*", lambda route: route.fulfill(json={
                "out_width": 320, "out_height": 180, "mime": "image/png", "data": preview,
            }))
            page.get_by_role("button", name="Computers / Share screen").click()
            page.get_by_role("button", name="Desk (online)").click()
            page.get_by_role("button", name="1 (1600 × 900)").click()
            image = page.get_by_alt_text("Monitor preview")
            box = image.bounding_box()
            page.mouse.move(box["x"] + 30, box["y"] + 30)
            page.mouse.down()
            page.mouse.move(box["x"] + 220, box["y"] + 140)
            page.mouse.up()
            selection = page.locator(".modal .pointer-events-none.absolute").bounding_box()
            self.assertAlmostEqual(selection["x"], box["x"] + 30, delta=2)
            self.assertAlmostEqual(selection["y"], box["y"] + 30, delta=2)
            self.assertAlmostEqual(selection["width"], 190, delta=2)
            self.assertAlmostEqual(selection["height"], 110, delta=2)
