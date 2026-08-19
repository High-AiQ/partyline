"""The receipts module: one door, fire-and-forget, never a tail-loop killer."""

import json
import unittest
from unittest.mock import patch

from partyline.adapters.receipts import BEGAN, ENDED, receipt


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ReceiptTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_hook_url_is_a_noop(self):
        with patch("urllib.request.urlopen") as urlopen:
            await receipt({}, ENDED)
        urlopen.assert_not_called()

    async def test_posts_the_event_as_a_hook_payload(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            await receipt({"hook_url": "http://host:1234/api/hooks/att/tok"}, BEGAN)

        self.assertEqual(captured["url"], "http://host:1234/api/hooks/att/tok")
        self.assertEqual(captured["body"], {"hookEventName": "UserPromptSubmit"})
        self.assertEqual(captured["timeout"], 5)

    async def test_a_failed_post_is_logged_but_swallowed(self):
        """A lost receipt degrades to the pre-receipt wedged badge; it must
        never raise into the transcript loop that emitted it — but it must be
        loud in the log, or a dead receipt path is invisible."""
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            with self.assertLogs("partyline.adapters.receipts", level="ERROR"):
                await receipt({"hook_url": "http://gone/", "name": "agent"}, ENDED)


if __name__ == "__main__":
    unittest.main()
