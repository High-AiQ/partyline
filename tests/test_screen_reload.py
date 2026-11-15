"""Page reload keeps the ordinary write, line scope, audit and follow-up read boundaries."""
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from partyline.mcp import tools_control
from partyline.screen_element_actions import ElementAction
from tests.window_grant_fixtures import WindowGrantFixture
from tests.test_window_snapshot import SnapshotFixture


class ReloadServerTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.device["chrome_dom"] = 4

    async def reload(self, ident="a", **extra):
        line = self.db.get_attachment(ident)["conv_id"]
        return await self.client.post(f"/api/conversations/{line}/screen-control/element-action",
            json={"action": "reload", "element_id": "page", **extra}, headers=self.machine(ident))

    async def test_reload_needs_no_snapshot_and_uses_existing_write_audit(self):
        await self.grant("a")
        self.sent.clear()
        result = await self.reload(then={})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "completed")
        self.assertIn("after", result.json())
        actions = [m for m in self.sent if m["type"] == "window_element_action"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["element_id"], "page")
        self.assertEqual(actions[0]["grant_id"], "g1")
        rows = self.db._exec("SELECT entry FROM screen_control_audit").fetchall()
        audit = [json.loads(r["entry"]) for r in rows if r["entry"].startswith("{")]
        self.assertTrue(any(r["operation"] == "screen_element_action" and r["grant"] == "g1" for r in audit))
        before = len(self.sent)
        self.assertEqual((await self.reload("b", window="g1")).status_code, 403)
        self.assertEqual(len(self.sent), before)
        with patch("partyline.screen_element_routes.core.deny_unless",
                   side_effect=HTTPException(403, "write denied")):
            self.assertEqual((await self.reload()).status_code, 403)
        self.assertEqual(len(self.sent), before)

    async def test_reload_parameters_and_catalog(self):
        await self.grant("a")
        self.sent.clear()
        self.assertEqual((await self.reload(element_id="old-page-id")).status_code, 409)
        self.assertEqual((await self.reload(value="new url")).status_code, 409)
        self.assertEqual(self.sent, [])
        self.assertEqual(ElementAction(action="reload", element_id="page").parameters(),
                         {"action": "reload", "element_id": "page"})
        self.assertIn("reload", tools_control.ELEMENT_ACTION_PROPERTIES["action"]["enum"])
        self.assertIn('element_id="page"', tools_control.ELEMENT_ACTION_NOTE)

    async def test_crash_metadata_survives_server_tree_capture_and_cached_answers(self):
        await self.grant("a")
        receive = self.receive
        async def answer(message):
            if message["type"] == "read_window_elements":
                self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                    "source": "uia", "page_state": "crashed", "recovery_hint": "reload",
                    "elements": [{"id": "reload", "name": "Reload", "control_type": "Button"}]})
            else:
                await receive(message)
        self.device["socket"].send_json = answer
        for _ in range(2):
            result = (await self.read("a")).json()
            self.assertEqual(result["source"], "uia")
            self.assertEqual(result["page_state"], "crashed")
            self.assertEqual(result["recovery_hint"], "reload")
        self.sent.clear()
        refused = (await self.act("a")).json()
        self.assertEqual(refused["status"], "failed")
        self.assertEqual(refused["error"], "reload")
        self.assertFalse(any(m["type"] == "window_element_action" for m in self.sent))


class SnapshotMetadataTests(SnapshotFixture, unittest.IsolatedAsyncioTestCase):
    async def test_window_snapshot_returns_crash_metadata(self):
        await self.grant("a")
        self.answer.update(source="uia", page_state="crashed", recovery_hint="reload")
        result = (await self.shot("a")).json()
        self.assertEqual(result["page_state"], "crashed")
        self.assertEqual(result["source"], "uia")
        self.assertEqual(result["recovery_hint"], "reload")


class ReloadCapabilityTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def test_old_helper_is_refused_without_dispatch(self):
        await self.grant("a")
        self.sent.clear()
        for capability in (0, 1, 2, 3):
            self.device["chrome_dom"] = capability
            response = await self.client.post("/api/conversations/alpha/screen-control/element-action",
                json={"action": "reload", "element_id": "page"}, headers=self.machine("a"))
            self.assertEqual(response.status_code, 409)
            self.assertIn("update the Partyline helper", response.json()["detail"])
        self.assertEqual(self.sent, [])
