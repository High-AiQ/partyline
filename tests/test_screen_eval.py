"""Eval uses the real grant authorization, capability and audit boundary."""
import json
import unittest
from unittest.mock import Mock

from partyline.mcp import catalog, tools_control
from partyline.screen_chrome_state import receive
from tests.window_grant_fixtures import WindowGrantFixture


class EvalServerTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def evaluate(self, ident="a", **extra):
        line = self.db.get_attachment(ident)["conv_id"]
        return await self.client.post(f"/api/conversations/{line}/screen-eval",
            headers=self.machine(ident), json={"expression": "privateCode()", **extra})

    async def test_eval_scoped_capability_and_text_free_audit(self):
        await self.grant("a")
        self.device["chrome_dom"] = 1
        self.sent.clear()
        receive = self.receive
        async def answer(message):
            if message["type"] == "window_eval":
                self.sent.append(message)
                self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                    "status": "completed", "source": "cdp", "result": {"answer": 42}})
            else:
                await receive(message)
        self.device["socket"].send_json = answer
        result = await self.evaluate()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["result"], {"answer": 42})
        self.assertEqual(self.sent[-1]["line_id"], "alpha")
        self.assertEqual(self.sent[-1]["agent"], "a")
        self.assertEqual(self.sent[-1]["grant_id"], "g1")
        audit = self.db._exec("SELECT entry FROM screen_control_audit").fetchall()
        entry = json.loads(audit[-1]["entry"])
        self.assertEqual(entry, dict(grant="g1", line="alpha", process="a", operation="screen_eval",
                                     input_length=13))
        self.assertNotIn("privateCode", audit[-1]["entry"])
        self.assertIn("g1", self.hub.elements.after_action)
        sent = len(self.sent)
        self.assertEqual((await self.evaluate("b", window="g1")).status_code, 403)
        self.assertEqual(len(self.sent), sent)
        self.device["chrome_dom"] = 0
        self.assertEqual((await self.evaluate()).status_code, 409)
        self.assertEqual((await self.evaluate(expression="x" * 16001)).status_code, 422)

    async def test_cdp_action_reply_stays_in_budget_with_large_unicode_state(self):
        await self.grant("a")
        receive = self.receive
        value = ""
        async def answer(message):
            if message["type"] == "window_element_action":
                self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                    "status": "completed", "source": "cdp", "element": {"value": value},
                    "timing": {"task_queue_ms": 2}})
            else:
                await receive(message)
        self.device["socket"].send_json = answer
        for value in ("x" * 4000, "💻" * 10000):
            with self.subTest(length=len(value)):
                response = await self.act("a")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["truncated"])
                self.assertIn("server_total_ms", response.json()["timing"])
                self.assertEqual(2, response.json()["timing"]["helper_task_queue_ms"])
                self.assertLessEqual(len(response.content), 4096)

    async def test_unconfirmed_eval_is_not_retried(self):
        await self.grant("a")
        self.device["chrome_dom"] = 1
        self.device["socket"].send_json = Mock(side_effect=OSError)
        result = await self.evaluate()
        self.assertEqual(result.json()["status"], "unconfirmed")
        self.assertEqual(self.device["socket"].send_json.call_count, 1)

    async def test_device_state_is_validated_and_pushed(self):
        from unittest.mock import AsyncMock
        self.hub._device_event = AsyncMock()
        await receive(self.hub, self.device, dict(state="awaiting_approval", detail="Approve in Chrome"))
        self.assertEqual(self.device["chrome"]["state"], "awaiting_approval")
        self.hub._device_event.assert_awaited_once_with(self.device, True)
        with self.assertRaises(ValueError):
            await receive(self.hub, self.device, dict(state="invented"))


class EvalToolsTests(unittest.TestCase):
    def test_tool_is_exposed_for_window_write_and_uses_eval_endpoint(self):
        state = dict(dynamic_screen_tools=True, screen_windows=True, actions=["write"])
        client = Mock(home="line")
        self.assertIn("screen_eval", {t["name"] for t in tools_control.tool_list(state)})
        self.assertIn("screen_eval", catalog.SCREEN)
        tools_control.call(client, "screen_eval", dict(expression="1+1"), state)
        client.request.assert_called_once_with("POST", "/api/conversations/line/screen-eval",
                                               {"expression": "1+1"}, timeout=60)
        with self.assertRaises(ValueError):
            tools_control.call(client, "screen_eval", dict(expression="1", frame="full"), state)
