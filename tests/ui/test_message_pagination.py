"""Browser proof for bounded first paint and anchored upward pagination."""

import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.uishot import ui_session  # noqa: E402


class MessagePaginationTest(unittest.TestCase):
    def test_first_paint_is_bounded_and_scrolling_up_preserves_the_reader(self):
        with ui_session(["long line"], handle="operator") as ui:
            page = ui.page
            conversations = page.request.get(
                f"{ui.base_url}/api/conversations", headers=ui.auth_headers
            ).json()
            conversation_id = conversations[0]["id"]
            for number in range(1, 46):
                response = page.request.put(
                    f"{ui.base_url}/api/conversations/{conversation_id}/topic",
                    data={"topic": f"history marker {number:02d}"},
                    headers=ui.auth_headers,
                )
                self.assertTrue(response.ok)

            page_urls = []
            page.on(
                "request",
                lambda request: page_urls.append(request.url)
                if f"/api/conversations/{conversation_id}/messages" in request.url
                else None,
            )
            with page.expect_response(
                lambda response: urlparse(response.url).path
                == f"/api/conversations/{conversation_id}"
            ) as detail_info:
                page.locator(".conv-row .conv").first.click()
            detail = detail_info.value.json()
            page.wait_for_selector("#composer")

            self.assertEqual(len(detail["messages"]), 20)
            self.assertTrue(detail["has_more_messages"])
            self.assertEqual(page.locator("#feed .msg").count(), 20)

            # Begin reading just inside the loading threshold. Capturing the
            # marker's top in the same JS turn beats the async fetch; after the
            # prepend it should remain at the same viewport coordinate.
            before = page.evaluate(
                """() => {
                  const feed = document.querySelector('#feed');
                  const marker = [...document.querySelectorAll('#feed .msg')]
                    .find(node => node.textContent.includes('history marker 26'));
                  feed.scrollTop = 100;
                  return marker.getBoundingClientRect().top;
                }"""
            )
            page.wait_for_function("() => document.querySelectorAll('#feed .msg').length === 40")
            after = page.locator("#feed .msg", has_text="history marker 26").bounding_box()["y"]

            self.assertAlmostEqual(before, after, delta=2)
            self.assertTrue(any("before_id=" in url and "limit=20" in url for url in page_urls))

            page.eval_on_selector("#feed", "feed => { feed.scrollTop = 0; }")
            page.wait_for_function("() => document.querySelectorAll('#feed .msg').length === 45")
            page.wait_for_timeout(100)
            self.assertEqual(page.locator("#feed .msg").count(), 45)

            # A live append must not yank someone reading history, while a
            # reader who returns to the bottom keeps the original follow mode.
            reading_top = page.eval_on_selector("#feed", "feed => feed.scrollTop")
            page.evaluate("() => window.partyline.room.say('live while reading')")
            page.wait_for_function("() => document.querySelectorAll('#feed .msg').length === 46")
            self.assertAlmostEqual(
                reading_top,
                page.eval_on_selector("#feed", "feed => feed.scrollTop"),
                delta=2,
            )

            page.eval_on_selector("#feed", "feed => { feed.scrollTop = feed.scrollHeight; }")
            page.evaluate("() => window.partyline.room.say('live while following')")
            page.wait_for_function("() => document.querySelectorAll('#feed .msg').length === 47")
            bottom_gap = page.eval_on_selector(
                "#feed", "feed => feed.scrollHeight - feed.scrollTop - feed.clientHeight"
            )
            self.assertLess(bottom_gap, 2)


if __name__ == "__main__":
    unittest.main()
