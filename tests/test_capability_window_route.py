"""Standing window access survives the HTTP capability contract and reaches MCP."""
import ast
import asyncio
import inspect
import textwrap
import unittest
from unittest.mock import AsyncMock, patch

from partyline import screen_capabilities
from partyline.hierarchy_contracts import CapabilityState
from partyline.hierarchy_routes import hierarchy_router
from partyline.mcp import catalog
from partyline.mcp.client import ApiError
from partyline.mcp.tools_screen import call as screen_call
from tests.window_grant_fixtures import WindowGrantFixture


class CapabilityWindowRouteTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def test_inherited_access_through_http_and_mcp(self):
        self.client._transport.app.include_router(hierarchy_router(self.runtime))
        self.db.create_conversation("child", "Child")
        self.db._exec("UPDATE conversations SET parent_id='alpha' WHERE id='child'")
        self.db.add_attachment("child", "child", "worker", "claude", ["shell"], "/tmp", "activation-child")
        self.db._exec("UPDATE screen_device_window_access SET owner_conv_id='alpha' WHERE device_id=?",
                      (self.device["id"],))
        headers = self.machine("child")
        loop = asyncio.get_running_loop()

        class Client:
            home = "child"

            def request(inner, method, path, payload=None, timeout=30):
                future = asyncio.run_coroutine_threadsafe(
                    self.client.request(method, path, json=payload, headers=headers), loop)
                response = future.result(timeout=5)
                self.assertEqual(200, response.status_code, response.text)
                return response.json()

            def capabilities(inner):
                return inner.request("GET", "/api/capabilities")

        client = Client()
        state = await asyncio.to_thread(client.capabilities)
        self.assertTrue(state["window_access"])
        self.assertTrue(state["dynamic_screen_tools"])
        names = {tool["name"] for tool in catalog.listed(state)}
        self.assertTrue({"screen_windows", "screen_attach_window"} <= names)
        request = AsyncMock(return_value={"windows": [{"id": "one", "title": "Editor"}]})
        with patch.object(self.hub.standing_windows, "request", request):
            result = await asyncio.to_thread(catalog.dispatch, client, "screen_windows", {}, state)
        self.assertEqual([{"id": "one", "title": "Editor"}], result["windows"])
        request.assert_awaited_once()
        self.assertEqual(self.device, request.await_args.args[0])
        self.assertEqual("child", request.await_args.kwargs["line_id"])

        self.device["window_access_enabled"] = False
        self.assertFalse((await asyncio.to_thread(client.capabilities))["window_access"])
        self.device["window_access_enabled"] = True
        self.hub.devices.clear()
        self.assertFalse((await asyncio.to_thread(client.capabilities))["window_access"])
        with self.assertRaisesRegex(ApiError, "no paired computer with window access on is connected"):
            screen_call(client, "screen_windows", {}, {"window_access": False}, "child")

    def test_all_capability_assignments_are_in_response_model(self):
        # Inspect all branches, including flags whose runtime prerequisites are absent here.
        keys = set()
        for function in (screen_capabilities.for_attachment, screen_capabilities.for_request):
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
                        and isinstance(node.value, ast.Name) and node.value.id == "state"
                        and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
                    keys.add(node.slice.value)
        missing = keys - CapabilityState.model_fields.keys()
        self.assertFalse(missing, missing)
