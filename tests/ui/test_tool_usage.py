"""Usage section: seeded real API, desktop/phone layout and review screenshots.

Run explicitly through scripts/capped-test; captures stay in /var/tmp, outside Git.
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


class UsageLayoutTest(unittest.TestCase):
    def test_seeded_summary_and_phone_layout(self):
        paths = []
        original = tempfile.mkstemp

        def remember(*args, **kwargs):
            fd, path = original(*args, **kwargs)
            paths.append(path)
            return fd, path

        with patch("scripts.uishot.tempfile.mkstemp", side_effect=remember), \
                ui_session(["Tool telemetry"], out_dir="/var/tmp/partyline-tool-usage",
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
            finally:
                db.close()
            records = []
            for tool, sub_op, action, tokens in (
                    ("screen_elements", "", "", [220, 260, 310, 450, 600]),
                    ("extras", "screen_element_action", "invoke", [80, 100, 140]),
                    ("get_media", "", "", [20, 20]),
                    ("captain", "set_goal", "", [40])):
                for index, count in enumerate(tokens):
                    records.append({"tool": tool, "sub_op": sub_op, "action": action,
                                    "result_bytes": count * 4, "result_chars": count * 4,
                                    "estimated_tokens": count, "timestamp": time.time(),
                                    "latency_ms": 10 + index * 5, "is_error": False,
                                    "query": tool == "screen_elements",
                                    "then": sub_op == "screen_element_action",
                                    "images": ([{"width": 750, "height": 1000,
                                                 "provider": "claude", "estimated_tokens": 1000}]
                                               if tool == "get_media" else [])})
            response = ui.page.request.post(ui.base_url + "/api/telemetry/tool-calls",
                                            data={"records": records}, headers={
                                                "Authorization": "Bearer " + credential})
            self.assertEqual(response.status, 200)
            response = ui.page.request.get(
                ui.base_url + "/api/telemetry/tool-calls/summary?conv_id=" + conv, headers=ui.auth_headers)
            self.assertEqual(response.status, 200)
            summary = response.json()
            Path("/var/tmp/partyline-tool-usage-summary.json").write_text(json.dumps(summary, indent=2))
            self.assertEqual([row["total_estimated_tokens"] for row in summary["rows"]],
                             [2040, 1840, 320, 40])
            menu = ui.open_row_menu()
            menu.get_by_text("management", exact=True).click()
            section = ui.page.get_by_role("region", name="Usage", exact=True)
            section.get_by_text("2,040", exact=True).wait_for()
            notice = ui.page.locator("#wireNotice")
            if notice.is_visible():
                notice.get_by_role("button", name="dismiss", exact=True).click()
                notice.wait_for(state="hidden")
            ui.element_shot("usage-desktop", 'section[aria-label="Usage"]')
            ui.page.set_viewport_size(NARROW_VIEWPORT)
            section.scroll_into_view_if_needed()
            self.assertTrue(section.evaluate("el => el.scrollWidth <= el.clientWidth"))
            self.assertLessEqual(section.bounding_box()["width"], NARROW_VIEWPORT["width"])
            gap = section.locator("thead").evaluate("""thead => {
                const rect = index => {
                    const range = document.createRange();
                    range.selectNodeContents(thead.querySelectorAll('th')[index]);
                    return range.getBoundingClientRect();
                };
                return rect(2).left - rect(1).right;
            }""")
            self.assertGreaterEqual(gap, 6, "column headers must remain visually separated on a phone")
            ui.element_shot("usage-phone", 'section[aria-label="Usage"]')
