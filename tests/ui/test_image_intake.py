"""Browser checks for the composer's native file-intake boundaries."""

import unittest

from scripts.uishot import ui_session


class ImageIntakeTest(unittest.TestCase):
    def test_drop_and_paste_share_the_attachment_preview_pipeline(self):
        with ui_session(["image line"]) as ui:
            page = ui.page
            with page.expect_response(
                lambda response: "/api/conversations/" in response.url
                and response.request.method == "GET"
            ):
                page.locator(".conv-row .conv").first.click()

            page.evaluate(
                """
                () => {
                  const composer = document.querySelector('#composer');
                  const transfer = new DataTransfer();
                  transfer.items.add(new File(['drop'], 'dropped.png', { type: 'image/png' }));
                  composer.dispatchEvent(new DragEvent('dragenter', {
                    bubbles: true, cancelable: true, dataTransfer: transfer
                  }));
                  window.partylineDrop = transfer;
                }
                """
            )
            page.locator(".drop-hint").wait_for(state="visible")
            page.evaluate(
                """
                () => document.querySelector('#composer').dispatchEvent(new DragEvent('drop', {
                  bubbles: true, cancelable: true, dataTransfer: window.partylineDrop
                }))
                """
            )
            page.get_by_text("dropped.png", exact=True).wait_for(state="visible")
            page.locator(".drop-hint").wait_for(state="detached")

            prevented = page.evaluate(
                """
                () => {
                  const transfer = new DataTransfer();
                  transfer.items.add(new File(['paste'], 'pasted.webp', { type: 'image/webp' }));
                  const event = new Event('paste', { bubbles: true, cancelable: true });
                  Object.defineProperty(event, 'clipboardData', { value: transfer });
                  document.querySelector('#input').dispatchEvent(event);
                  return event.defaultPrevented;
                }
                """
            )
            self.assertTrue(prevented)
            page.get_by_text("pasted.webp", exact=True).wait_for(state="visible")

            ordinary_paste_prevented = page.evaluate(
                """
                () => {
                  const event = new Event('paste', { bubbles: true, cancelable: true });
                  const transfer = new DataTransfer();
                  transfer.setData('text/plain', 'keep ordinary paste native');
                  Object.defineProperty(event, 'clipboardData', { value: transfer });
                  document.querySelector('#input').dispatchEvent(event);
                  return event.defaultPrevented;
                }
                """
            )
            self.assertFalse(ordinary_paste_prevented)


if __name__ == "__main__":
    unittest.main()
