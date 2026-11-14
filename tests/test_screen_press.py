"""Press follows real window-grant authorization and rejects old helpers before any exchange."""
import unittest
from unittest.mock import AsyncMock

from pydantic import ValidationError

from partyline.mcp import tools_control
from partyline.screen_element_actions import ElementAction
from tests.window_grant_fixtures import WindowGrantFixture


class PressServerTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def press(self, ident="a", **extra):
        line = self.db.get_attachment(ident)["conv_id"]
        return await self.client.post(f"/api/conversations/{line}/screen-control/element-action",
            json={"element_id": "g1-element", "action": "press", "key": "enter", **extra},
            headers=self.machine(ident))

    async def test_new_helper_routes_press_and_old_helper_refused_without_exchange(self):
        await self.grant("a")
        self.device["helper_version"] = "99.0.0"  # capability, never a guessed version threshold
        self.sent.clear()
        response = await self.press()
        self.assertEqual(409, response.status_code)
        self.assertEqual("update the Partyline helper to use press", response.json()["detail"])
        self.assertEqual([], self.sent)
        self.device["press"] = 1
        response = await self.press()
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("press", self.sent[-1]["action"])
        self.assertEqual("enter", self.sent[-1]["key"])
        self.assertEqual("g1", self.sent[-1]["grant_id"])

    async def test_another_lines_window_and_invalid_keys_are_refused(self):
        await self.grant("a")
        self.device["press"] = 1
        self.sent.clear()
        self.assertEqual(403, (await self.press("b", window="g1")).status_code)
        for key in ("ctrl+enter", "a", "ENTER"):
            self.assertEqual(422, (await self.press(key=key)).status_code)
        self.assertEqual(422, (await self.press(modifiers=["ctrl"])).status_code)
        self.assertEqual([], self.sent)

    async def test_no_effect_still_runs_then_with_fake_settle(self):
        await self.grant("a")
        self.device["press"] = 1
        self.hub.elements.settle = AsyncMock()
        receive = self.receive
        async def answer(message):
            if message["type"] == "window_element_action":
                self.sent.append(message)
                self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                    "status": "no_effect", "hint": "No change yet", "posted": 3})
            else:
                await receive(message)
        self.device["socket"].send_json = answer
        result = (await self.press(then={})).json()
        self.assertEqual("no_effect", result["status"])
        self.assertIn("after", result)
        self.assertIn("diff", result["after"])
        self.hub.elements.settle.assert_awaited_once()


class PressSchemaTests(unittest.TestCase):
    def test_api_and_mcp_reject_unrelated_parameters(self):
        self.assertEqual({"element_id": "e", "action": "press", "key": "tab"},
                         ElementAction(element_id="e", action="press", key="tab").parameters())
        for fields in ({}, {"key": "enter", "value": "text"}):
            with self.assertRaises(ValueError):
                ElementAction(element_id="e", action="press", **fields).parameters()
        with self.assertRaises(ValidationError):
            ElementAction(element_id="e", action="press", key="ctrl+enter")
        client = AsyncMock(home="line")
        with self.assertRaises(ValueError):
            tools_control.call(client, "screen_element_action",
                               {"element_id": "e", "action": "press", "key": "space"}, {"actions": ["write"]})
