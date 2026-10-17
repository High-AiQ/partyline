"""Browser regression for the image viewer's large-content modal layout."""

import unittest

from scripts.uishot import ui_session


# A seeded fixture, not an upload: `kind` is what the feed branches on, and the
# routed SVG URLs give the modal real pixels without requiring stored media.
# A real svg upload would arrive as kind "file" — Pillow decides what an image is.
IMAGE = {
    "id": "image-1",
    "kind": "image",
    "filename": "signal-map.svg",
    "title": "Signal map",
    "description": "A test image",
    "mime": "image/svg+xml",
    "width": 800,
    "height": 560,
    "bytes": 100,
    "thumb": None,
    "slim": {"mime": "image/webp", "width": 800, "height": 560, "bytes": 80},
    "urls": {
        "original": "/viewer-fixture/original.svg",
        "thumb": "/viewer-fixture/thumb.svg",
        "slim": "/viewer-fixture/slim.svg",
    },
}


class ImageViewerLayoutTest(unittest.TestCase):
    def test_large_image_cannot_crush_header_or_close_target(self):
        """The image is deliberately taller than the modal's available body.

        A flex-shrinking header still exists in the DOM, so visibility alone is
        a false-positive; its measured box and the close target must survive.
        """
        with ui_session(["image line"]) as ui:
            page = ui.page
            page.route("**/viewer-fixture/*.svg*", lambda route: route.fulfill(
                content_type="image/svg+xml",
                body='<svg xmlns="http://www.w3.org/2000/svg" width="800" height="560">'
                     '<rect width="800" height="560" fill="#d98e4a"/></svg>'))
            with page.expect_response(
                lambda response: "/api/conversations/" in response.url
                and response.request.method == "GET"
            ):
                page.locator(".conv-row .conv").first.click()
            message = {
                "id": 101,
                "conv_id": page.evaluate("() => window.partyline.room.conversation.id"),
                "sender": "greg",
                "sender_type": "human",
                "body": "A caption\n📷 Signal map · 800×560 · thumb: test",
                "created_at": 1_700_000_000,
                "files": [IMAGE],
            }
            page.evaluate("(value) => { window.partyline.room.messages = [value]; }", message)
            self.assertEqual(page.locator(".grid .tile img").get_attribute("src").split("?")[0],
                             IMAGE["urls"]["thumb"])
            page.locator(".grid .tile").click()
            self.assertEqual(page.locator(".stage img").get_attribute("src").split("?")[0],
                             IMAGE["urls"]["slim"])

            modal = page.locator(".modal").bounding_box()
            header = page.locator(".modal header").bounding_box()
            close = page.locator(".modal .close").bounding_box()
            self.assertIsNotNone(modal)
            self.assertIsNotNone(header)
            self.assertIsNotNone(close)
            self.assertGreaterEqual(header["height"], 44)
            self.assertGreaterEqual(close["width"], 44)
            self.assertGreaterEqual(close["height"], 44)
            self.assertGreaterEqual(header["y"], max(modal["y"], 0), (modal, header))
            self.assertLessEqual(header["y"] + header["height"], modal["y"] + modal["height"])
            page.locator(".modal .close").click()
            page.locator(".modal").wait_for(state="detached")


if __name__ == "__main__":
    unittest.main()
