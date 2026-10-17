"""Real multi-upload viewer geometry, original downloads and gallery regression.

Set PARTYLINE_VIEWER_EVIDENCE to a durable directory to retain captures/downloads.
Run through scripts/capped-test; the browser needs a process-tree memory cap.
"""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from partyline.mcp.client import PartylineClient
from scripts.uishot import ui_session

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "multi_upload"


class MultiUploadViewerTest(unittest.TestCase):
    def assert_inside(self, inner, outer):
        for axis, size in (("x", "width"), ("y", "height")):
            self.assertGreaterEqual(inner[axis], outer[axis] - 1, (inner, outer))
            self.assertLessEqual(inner[axis] + inner[size], outer[axis] + outer[size] + 1,
                                 (inner, outer))

    def assert_geometry(self, page, viewport):
        image = page.locator(".stage img")
        page.wait_for_function("() => { const i = document.querySelector('.stage img'); "
                               "return i?.complete && i.naturalWidth > 0; }")
        page.evaluate("() => { for (const a of document.getAnimations()) a.finish(); }")
        dimensions = image.evaluate("i => ({width: i.naturalWidth, height: i.naturalHeight})")
        box = image.bounding_box()
        self.assertGreater(box["width"], 0)
        self.assertGreater(box["height"], 0)
        self.assertAlmostEqual(box["width"] / box["height"],
                               dimensions["width"] / dimensions["height"], delta=0.01)
        screen = {"x": 0, "y": 0, **viewport}
        self.assert_inside(box, screen)
        self.assert_inside(box, page.locator(".stage").bounding_box())
        for selector in (".previous", ".next", ".download", ".close", ".position"):
            control = page.locator(".modal " + selector)
            self.assertTrue(control.is_visible(), selector)
            self.assert_inside(control.bounding_box(), screen)
            self.assert_inside(control.bounding_box(), page.locator(".modal").bounding_box())
        # No scrolling should be needed to reach the viewer's controls.
        self.assertTrue(page.locator(".modal .content").evaluate(
            "el => el.scrollHeight <= el.clientHeight + 1"))
        return box, dimensions

    def test_real_uploads_fit_and_download_at_desktop_and_narrow_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(os.environ.get("PARTYLINE_VIEWER_EVIDENCE", temp))
            with ui_session(["viewer regression"], out_dir=out, freeze_animations=True) as ui:
                page = ui.page
                page.set_default_timeout(5000)
                with page.expect_response(lambda r: "/api/conversations/" in r.url
                                          and r.request.method == "GET"):
                    page.locator(".conv-row .conv").first.click()
                conv_id = page.evaluate("() => window.partyline.room.conversation.id")
                client = PartylineClient.__new__(PartylineClient)
                client.connection = {"api": ui.base_url, "conversation_id": conv_id,
                                     "token": ui.auth_headers["Authorization"].removeprefix("Bearer ")}
                images = sorted(FIXTURES.glob("*-card.*"))
                client.upload_files(conv_id, [str(p) for p in images], client_key="viewer-images")
                page.wait_for_selector(".tile:nth-child(6)")
                self.assertEqual(page.locator(".tile").count(), 6)
                # The host's sandbox preflight warning is unrelated to this test.
                page.locator("#fenceUnavailable").evaluate_all("nodes => nodes.forEach(n => n.remove())")
                page.wait_for_function("() => [...document.querySelectorAll('.tile img')]"
                                       ".every(i => i.complete && i.naturalWidth > 0)")
                ui.shot("05-fitted-six-image-gallery")
                for name, viewport in (("desktop", {"width": 1280, "height": 800}),
                                       ("narrow", {"width": 390, "height": 844})):
                    page.set_viewport_size(viewport)
                    for index, orientation in ((3, "landscape"), (5, "portrait")):
                        page.locator(".tile").nth(index).click()
                        box, natural = self.assert_geometry(page, viewport)
                        self.assertEqual(page.locator(".position").inner_text(), f"{index + 1} / 6")
                        ui.shot(f"06-{name}-{orientation}-fitted")
                        with page.expect_download() as pending:
                            page.locator(".modal .download").click()
                        download = pending.value
                        self.assertEqual(download.suggested_filename, images[index].name)
                        destination = out / f"downloaded-{name}-{images[index].name}"
                        download.save_as(destination)
                        self.assertEqual(destination.read_bytes(), images[index].read_bytes())
                        print(name, orientation, "rendered", box, "natural", natural,
                              "download SHA256", hashlib.sha256(destination.read_bytes()).hexdigest())
                        page.locator(".next").click()
                        self.assertEqual(page.locator(".position").inner_text(), f"{(index + 1) % 6 + 1} / 6")
                        page.locator(".previous").click()
                        self.assertEqual(page.locator(".position").inner_text(), f"{index + 1} / 6")
                        page.locator(".modal .close").click()
                        page.locator(".modal").wait_for(state="detached")
                page.set_viewport_size({"width": 1280, "height": 800})
                texts = sorted(FIXTURES.glob("*.txt"))
                client.upload_files(conv_id, [str(p) for p in texts], client_key="viewer-texts")
                page.wait_for_selector(".card:nth-child(6)")
                self.assertEqual(page.locator(".card").count(), 6)
                self.assertEqual(page.locator(".tile").count(), 6)
                for path in texts:
                    self.assertTrue(page.get_by_role("button", name=f"download {path.name}").is_visible())
                ui.shot("07-fitted-six-text-attachments")


if __name__ == "__main__":
    unittest.main()
