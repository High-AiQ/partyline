"""MCP listings fit one bounded reply in whole records."""

import json
import unittest

from partyline.mcp import pages, tools_core
from partyline.mcp.render import MAX_TEXT, render
from tests.test_mcp import FakeClient


def message(ident, body="x" * 900):
    return {"id": ident, "conv_id": "home", "sender": "greg", "sender_type": "human", "body": body,
            "created_at": 1.0, "files": [], "source_attachment_id": None, "source_conv_id": None,
            "audience_attachment_id": None, "bridge_id": None, "reactions": [], "replayed": False}


class MessagePageTests(unittest.TestCase):
    def page(self, client, args, messages, has_more=False):
        client.request = lambda method, path, payload=None: {"messages": messages, "has_more": has_more}
        return tools_core.call(client, "read_messages", args, client.state)

    def test_a_small_page_passes_through_without_its_unset_fields(self):
        page = self.page(FakeClient(), {}, [message(1, "hello"), message(2, "there")])
        self.assertEqual(page, {"has_more": False, "messages": [
            {"id": ident, "conv_id": "home", "sender": "greg", "sender_type": "human", "body": body,
             "created_at": 1.0} for ident, body in ((1, "hello"), (2, "there"))]})

    def test_the_latest_page_keeps_its_newest_whole_messages_and_says_where_to_resume(self):
        """A 50-message page was cut mid-record at 20,000 characters, `has_more` and all."""
        page = self.page(FakeClient(), {"limit": 50}, [message(ident) for ident in range(1, 51)])
        kept = [row["id"] for row in page["messages"]]
        self.assertEqual(kept, list(range(kept[0], 51)))  # a run ending at the newest
        self.assertGreater(len(kept), 10)
        self.assertEqual((page["has_more"], page["omitted"], page["resume"]),
                         (True, 50 - len(kept), {"before_id": kept[0]}))
        text = render(page, "http://127.0.0.1:8643")
        self.assertLess(len(text), MAX_TEXT)
        self.assertEqual(json.loads(text)["messages"][-1]["id"], 50)

    def test_a_forward_page_keeps_its_oldest_messages(self):
        page = self.page(FakeClient(), {"after_id": 10, "limit": 50},
                         [message(ident) for ident in range(11, 61)])
        kept = [row["id"] for row in page["messages"]]
        self.assertEqual(kept, list(range(11, kept[-1] + 1)))
        self.assertEqual(page["resume"], {"after_id": kept[-1]})

    def test_a_page_around_a_message_keeps_that_message_and_both_its_sides(self):
        """Trimmed like the latest page, a long tail pushed the message asked for off the reply."""
        client = FakeClient()
        rows = [message(ident, "x" * 300) for ident in range(80, 100)]
        rows += [message(100, "the target")] + [message(ident, "y" * 1200) for ident in range(101, 121)]
        client.request = lambda method, path, payload=None: {
            "messages": rows, "has_more_before": False, "has_more_after": True}
        page = tools_core.call(client, "read_messages", {"around_id": 100, "limit": 20}, client.state)
        kept = [row["id"] for row in page["messages"]]
        self.assertIn(100, kept)
        self.assertEqual(kept, list(range(kept[0], kept[-1] + 1)))
        self.assertLess(kept[0], 100)
        self.assertGreater(kept[-1], 100)
        self.assertEqual(page["resume"], {"before_id": kept[0], "after_id": kept[-1]})
        self.assertEqual((page["has_more_before"], page["has_more_after"]), (True, True))
        self.assertNotIn("has_more", page)
        self.assertLess(len(render(page, "http://127.0.0.1:8643")), MAX_TEXT)
        long_both = [message(ident, "z" * 1500) for ident in range(1, 42)]
        client.request = lambda method, path, payload=None: {
            "messages": long_both, "has_more_before": False, "has_more_after": False}
        page = tools_core.call(client, "read_messages", {"around_id": 21, "limit": 20}, client.state)
        kept = [row["id"] for row in page["messages"]]
        self.assertLessEqual(abs((21 - kept[0]) - (kept[-1] - 21)), 1)  # grown evenly outwards
        self.assertEqual(page["resume"], {"before_id": kept[0], "after_id": kept[-1]})
        self.assertEqual((page["has_more_before"], page["has_more_after"]), (True, True))
        small = self.page(FakeClient(), {"around_id": 2}, [message(1, "a"), message(2, "b")])
        self.assertNotIn("resume", small)

    def test_one_message_larger_than_the_reply_is_still_returned(self):
        page = self.page(FakeClient(), {}, [message(1), message(2, "y" * 50_000)])
        self.assertEqual([row["id"] for row in page["messages"]], [2])
        self.assertEqual(page["omitted"], 1)

    def test_a_reply_that_is_not_a_page_is_left_alone(self):
        self.assertEqual(pages.message_page({"detail": "refused"}, False), {"detail": "refused"})
        self.assertEqual(pages.message_page([1, 2], True), [1, 2])
        self.assertEqual(pages.compact("text"), "text")


class WhoamiTests(unittest.TestCase):
    def test_a_long_lived_root_lists_its_live_children_and_counts_the_retired(self):
        """193 retired lines were 14.5 KB of every `whoami` on the root they were found on."""
        client = FakeClient()
        detail = client.request("GET", "/api/conversations/home")
        children = [{"id": f"old-{index}", "name": f"retired-{index}", "archived_at": 5.0}
                    for index in range(193)] + [{"id": "live", "name": "current", "archived_at": None}]
        client.request = lambda method, path, payload=None: (
            children if path.endswith("/children") else detail)
        result = tools_core.call(client, "whoami", {}, client.state)
        self.assertEqual(result["children"], [{"id": "live", "name": "current"}])
        self.assertEqual(result["retired_children"], 193)
        self.assertEqual(pages.live_children({"detail": "refused"}), ([], 0))


if __name__ == "__main__":
    unittest.main()
