"""Server-side validation and MCP contract of the pattern actions."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from partyline.mcp import tools_control
from partyline.screen_element_actions import ElementAction, element_action
from partyline.screen_elements import ElementsHub


def body(action, **fields):
    return ElementAction(element_id="target", action=action, **fields)


class ParameterTests(unittest.TestCase):
    def test_each_action_takes_exactly_its_parameters(self):
        good = [("invoke", {}), ("select", {}), ("expand", {}), ("window_close", {}),
                ("set_value", {"value": ""}), ("scroll", {"direction": "up", "amount": "small"}),
                ("set_scroll_percent", {"horizontal_percent": 0}),
                ("set_scroll_percent", {"horizontal_percent": 1, "vertical_percent": 99.5}),
                ("set_range_value", {"number": 0}), ("window_move", {"x": -5, "y": 0}),
                ("window_resize", {"width": 300, "height": 200})]
        for action, fields in good:
            with self.subTest(action=action):
                self.assertEqual({"element_id": "target", "action": action, **fields},
                                 body(action, **fields).parameters())
        bad = [("set_value", {}), ("scroll", {"direction": "up"}), ("set_scroll_percent", {}),
               ("set_range_value", {}), ("window_move", {"x": 1}), ("window_resize", {"width": 1}),
               ("invoke", {"value": "x"}), ("scroll", {"direction": "up", "amount": "small", "x": 1}),
               ("select", {"number": 1})]
        for action, fields in bad:
            with self.subTest(action=action, fields=fields), self.assertRaises(ValueError):
                body(action, **fields).parameters()

    def test_schema_bounds(self):
        for action, fields in [("scroll", {"direction": "diagonal", "amount": "small"}),
                               ("set_scroll_percent", {"vertical_percent": 101}),
                               ("set_range_value", {"number": float("inf")}),
                               ("window_resize", {"width": 0, "height": 5}),
                               ("window_move", {"x": 40000, "y": 0}), ("drag", {})]:
            with self.subTest(action=action), self.assertRaises(ValidationError):
                body(action, **fields)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_parameters_reach_the_helper_and_invalid_ones_are_not_charged(self):
        sent = asyncio.Queue()
        socket = SimpleNamespace(send_json=lambda message: sent.put(message))
        share, device = SimpleNamespace(share_id="share"), {"id": "pc", "socket": socket}
        grant = SimpleNamespace(status="active", holder="agent")
        spend = Mock()
        control = SimpleNamespace(target=lambda _: (share, device), grants={"share": grant}, _spend=spend)
        elements = ElementsHub(SimpleNamespace(devices={}))
        hub = SimpleNamespace(control=control, elements=elements)
        with patch("partyline.screen_element_actions.request_principal",
                   return_value=SimpleNamespace(name="agent")), \
             patch("partyline.screen_element_actions.deny_unless"):
            with self.assertRaises(HTTPException) as error:
                await element_action(SimpleNamespace(db=None), hub, "line", body("scroll"), None)
            self.assertEqual(409, error.exception.status_code)
            self.assertIn("direction", error.exception.detail)
            spend.assert_not_called()
            task = asyncio.create_task(element_action(
                SimpleNamespace(db=None), hub, "line", body("window_move", x=10, y=20), None))
            request = await sent.get()
            self.assertEqual({"x": 10, "y": 20, "action": "window_move", "element_id": "target"},
                             {k: v for k, v in request.items() if k in ("x", "y", "action", "element_id")})
            self.assertNotIn("value", request)
            elements.receive(device, {"request_id": request["request_id"], "status": "completed"})
            self.assertEqual("completed", (await task)["status"])
            spend.assert_called_once()


class McpContractTests(unittest.TestCase):
    def test_schema_lists_every_action_and_validates_parameters(self):
        tool = next(item for item in tools_control.tool_list({"actions": ["write"]})
                    if item["name"] == "screen_element_action")
        actions = tool["inputSchema"]["properties"]["action"]["enum"]
        for expected in ("select", "expand", "collapse", "scroll", "set_scroll_percent", "scroll_into_view",
                         "set_range_value", "window_close", "window_move", "window_resize"):
            self.assertIn(expected, actions)
        self.assertNotIn("drag", actions)
        self.assertIn("screen_drag", tool["description"])
        calls = []
        client = SimpleNamespace(home="line", request=lambda *args, **kw: calls.append(args) or {})
        args = {"element_id": "a", "action": "scroll", "direction": "down", "amount": "large"}
        tools_control.call(client, "screen_element_action", args, {"actions": ["write"]})
        self.assertEqual(args, calls[0][2])
        for bad in ({"direction": "sideways"}, {"width": 0}, {"number": "5"}, {"extra": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tools_control.call(client, "screen_element_action", {**args, **bad}, {"actions": ["write"]})
