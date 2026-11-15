"""Computer use: seeded aggregate API, disclosure, desktop/phone layout and screenshots.

Run explicitly; captures stay in /var/tmp, outside Git.
"""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from partyline import auth_store
from partyline.db import Db
from scripts.uishot import NARROW_VIEWPORT, ui_session


class ComputerUsageLayoutTest(unittest.TestCase):
    def test_seeded_summary_and_phone_layout(self):
        paths = []
        original = tempfile.mkstemp

        def remember(*args, **kwargs):
            fd, path = original(*args, **kwargs)
            paths.append(path)
            return fd, path

        with patch("scripts.uishot.tempfile.mkstemp", side_effect=remember), \
                ui_session(["Computer telemetry"], out_dir="/var/tmp/partyline-computer-use",
                           freeze_animations=True) as ui:
            # Isolate layout from the nested-sandbox preflight banner. This browser
            # fixture changes no server permissions and launches no CLI.
            ui.page.route("**/api/fence/status", lambda route: route.fulfill(json={
                "ok": True, "backend": "fixture", "platform": "test", "reason": "", "remedy": ""}))
            ui.page.reload()
            ui.page.wait_for_selector(".conv-row")
            db = Db(paths[0])
            try:
                conv = db.list_conversations()[0]["id"]
                db.add_attachment("usage-fixture", conv, "fixture", "claude", ["fixture"], "/tmp")
                credential = auth_store.ensure_api_token(db, "usage-fixture")
                db._exec(
                    """INSERT INTO turn_usage(conv_id, attachment_id, adapter, response_id, input_tokens,
                       cache_read_tokens, cache_write_tokens, output_tokens, total_tokens, calls, timestamp,
                       model_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (conv, "usage-fixture", "claude", "computer-response", 100, 1000, 200, 300, 1600,
                     json.dumps(["Bash", "screen_click", "extras:screen_elements"]), time.time(), 1250),
                )
            finally:
                db.close()
            records = []
            for tool, sub_op, action, tokens in (
                    ("screen_elements", "", "", [220, 260, 310, 450, 600]),
                    ("extras", "screen_element_action", "invoke", [80, 100, 140]),
                    ("get_media", "", "", [20, 20]),
                    ("captain", "set_goal", "", [40])):
                for index, count in enumerate(tokens):
                    images = []
                    if (tool == "screen_elements" or tool == "get_media") and index == 0:
                        images = [{"width": 750, "height": 1000, "provider": "claude",
                                   "estimated_tokens": 1000}]
                    records.append({"tool": tool, "sub_op": sub_op, "action": action,
                                    "result_bytes": count * 4, "result_chars": count * 4,
                                    "estimated_tokens": count, "timestamp": time.time(),
                                    "latency_ms": 10 + index * 5, "is_error": False, "outcome": "ok",
                                    "media_source": ("screen" if tool == "get_media" and index == 0
                                                     else "other"),
                                    "query": tool == "screen_elements",
                                    "then": sub_op == "screen_element_action", "images": images})
            response = ui.page.request.post(ui.base_url + "/api/telemetry/tool-calls",
                                            data={"records": records}, headers={
                                                "Authorization": "Bearer " + credential})
            self.assertEqual(response.status, 200)
            response = ui.page.request.get(
                ui.base_url + "/api/telemetry/computer-use/summary?conv_id=" + conv, headers=ui.auth_headers)
            self.assertEqual(response.status, 200)
            summary = response.json()
            Path("/var/tmp/partyline-computer-use-summary.json").write_text(json.dumps(summary, indent=2))
            self.assertEqual((summary["responses"], summary["calls"], summary["actions"], summary["reads"]),
                             (1, 8, 3, 5))
            self.assertEqual((summary["total_tokens"], summary["images"], summary["image_tokens"]),
                             (1600, 2, 2000))
            menu = ui.open_row_menu()
            menu.get_by_text("management", exact=True).click()
            section = ui.page.get_by_role("region", name="Computer use", exact=True)
            section.get_by_text("1,600 tokens", exact=False).wait_for()
            section.locator("summary").click()
            section.get_by_text("2,000 estimated image tokens", exact=False).wait_for()
            section.locator("[data-cache-tokens]").hover()
            tip = ui.page.get_by_role("tooltip").filter(has_text="1,000 cache read + 200 cache write")
            tip.wait_for(state="visible")
            ui.shot("computer-use-tooltip")
            section.locator("h3").hover()
            tip.wait_for(state="hidden")
            notice = ui.page.locator("#wireNotice")
            if notice.is_visible():
                notice.get_by_role("button", name="dismiss", exact=True).click()
                notice.wait_for(state="hidden")
            ui.element_shot("computer-use-desktop", 'section[aria-label="Computer use"]')
            ui.page.set_viewport_size(NARROW_VIEWPORT)
            section.scroll_into_view_if_needed()
            self.assertTrue(section.evaluate("el => el.scrollWidth <= el.clientWidth"))
            self.assertLessEqual(section.bounding_box()["width"], NARROW_VIEWPORT["width"])
            ui.element_shot("computer-use-phone", 'section[aria-label="Computer use"]')
