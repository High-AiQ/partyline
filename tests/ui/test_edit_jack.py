"""Browser coverage for changing a stopped jack's next launch command."""

import unittest

from scripts.uishot import ui_session


class EditJackTest(unittest.TestCase):
    def test_only_a_stopped_jack_can_open_a_prefilled_editor_and_save(self):
        with ui_session(["edit line"], handle="operator") as ui:
            page = ui.page
            with page.expect_response(
                lambda response: "/api/conversations/" in response.url
                and response.request.method == "GET"
            ):
                page.locator(".conv-row .conv").first.click()
            page.wait_for_selector("#composer")
            page.wait_for_function("() => window.partyline.wire.ready")
            conversation_id = page.evaluate("() => window.partyline.room.conversation.id")

            attached = page.request.post(
                f"{ui.base_url}/api/conversations/{conversation_id}/attachments",
                data={
                    "name": "worker",
                    "adapter": "raw",
                    "command": "/bin/sleep 60",
                    "cwd": "/tmp",
                },
            )
            self.assertTrue(attached.ok, attached.text())
            attachment_id = attached.json()["id"]
            jack = page.locator(".jack").filter(has_text="worker")
            jack.wait_for(state="visible")

            edit = jack.locator("button[title='change the command used on next resume']")
            self.assertEqual(edit.count(), 0, "a live jack must not offer command editing")

            detached = page.request.delete(f"{ui.base_url}/api/attachments/{attachment_id}")
            self.assertTrue(detached.ok, detached.text())
            edit.wait_for(state="visible")
            edit.click()

            modal = page.locator(".modal")
            modal.wait_for(state="visible")
            command = modal.locator("#editJackCommand")
            self.assertEqual(command.input_value(), "/bin/sleep 60")
            command.fill('/bin/sleep 30 --label "two words"')

            with page.expect_response(
                lambda response: response.url.endswith(f"/api/attachments/{attachment_id}")
                and response.request.method == "PATCH"
            ) as saved:
                modal.get_by_role("button", name="save command").click()
            self.assertTrue(saved.value.ok, saved.value.text())
            modal.wait_for(state="detached")

            page.wait_for_function(
                """id => {
                  const jack = window.partyline.room.attachments.find(candidate => candidate.id === id);
                  return JSON.stringify(jack?.command) ===
                    JSON.stringify(['/bin/sleep', '30', '--label', 'two words']);
                }""",
                arg=attachment_id,
            )


if __name__ == "__main__":
    unittest.main()
