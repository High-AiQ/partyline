"""Browser regression for Greg's mobile bug (2.20): the approvals banner used
to render after the full-height app grid, so on a phone it sat below the
viewport and the composer never moved for it — it was findable only by
scrolling. The banner now takes flow space in the column directly above the
composer: the feed shrinks, and the banner is on screen at scroll position 0.

The pending request is seeded straight into the throwaway database (the same
row a machine's filing would create); opening the conversation loads the
approvals list and renders it.

Run explicitly: ``uv run python -m unittest tests/ui/test_mobile_approvals.py``.
"""

import json
import sqlite3
import time
import urllib.request
import unittest

from scripts.ui_auth import post_json
from scripts.uishot import NARROW_VIEWPORT, VIEWPORT, ui_session


def seed_pending_request(ui) -> None:
    """Insert the pending write-set row into the throwaway database."""
    token = ui.auth_headers["Authorization"].removeprefix("Bearer ")
    db = None
    with open(f"/proc/{ui.server.pid}/environ", "rb") as fh:
        for entry in fh.read().split(b"\0"):
            if b"PARTYLINE_DB=" in entry:
                db = entry.split(b"=", 1)[1].decode()
    request = urllib.request.Request(f"{ui.base_url}/api/conversations")
    request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request) as response:
        conv_id = json.load(response)[0]["id"]
    con = sqlite3.connect(db, timeout=10)
    con.execute(
        "INSERT OR REPLACE INTO conversation_write_grant_requests"
        "(conv_id,id,path,requester,requester_attachment_id,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (conv_id, "req-mobile", "/var/run/docker.sock", "worker", None, time.time()))
    con.commit()
    con.close()


class MobileApprovalsTest(unittest.TestCase):
    def open_conversation(self, ui):
        ui.page.locator(".conv-row").first.click()
        ui.page.wait_for_selector("#composer", state="visible")

    def test_banner_sits_above_the_composer_at_phone_width(self):
        with ui_session(["alpha line"]) as ui:
            self.open_conversation(ui)
            seed_pending_request(ui)
            # Re-opening the conversation is what loads the approvals list.
            ui.page.reload()
            ui.settle()
            self.open_conversation(ui)
            ui.page.wait_for_selector("#approvalsPending", state="visible")

            banner = ui.page.locator("#approvalsPending").bounding_box()
            composer = ui.page.locator("#composer").bounding_box()
            self.assertIsNotNone(banner)
            self.assertIsNotNone(composer)
            # Fully on screen at scroll position 0 — no scrolling to find it.
            self.assertGreaterEqual(banner["y"], 0)
            self.assertLessEqual(banner["y"] + banner["height"],
                                 NARROW_VIEWPORT["height"])
            # In the bottom stack, directly above the composer.
            self.assertLessEqual(banner["y"] + banner["height"], composer["y"] + 1)
            self.assertEqual(ui.page.evaluate("window.scrollY"), 0)

    def test_desktop_places_the_banner_above_the_composer_too(self):
        with ui_session(["alpha line"], viewport=VIEWPORT) as ui:
            self.open_conversation(ui)
            seed_pending_request(ui)
            ui.page.reload()
            ui.settle()
            self.open_conversation(ui)
            ui.page.wait_for_selector("#approvalsPending", state="visible")
            banner = ui.page.locator("#approvalsPending").bounding_box()
            composer = ui.page.locator("#composer").bounding_box()
            self.assertLessEqual(banner["y"] + banner["height"], composer["y"] + 1)


if __name__ == "__main__":
    unittest.main()
