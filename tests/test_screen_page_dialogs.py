"""Dialog input follows existing server grants, parameter validation and MCP contracts."""
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from partyline.mcp import tools_control
from partyline.screen_element_actions import ElementAction
from tests.window_grant_fixtures import WindowGrantFixture


class DialogParameters(unittest.TestCase):
    def test_explicit_boolean_and_page_target_and_no_foreign_parameters(self):
        for accept in (True, False):
            body = ElementAction(element_id="page", action="dialog", accept=accept, prompt_text="")
            self.assertEqual(body.parameters(), dict(element_id="page", action="dialog",
                                                     accept=accept, prompt_text=""))
        for fields in ({}, {"prompt_text": "text"}, {"accept": False, "key": "enter"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ElementAction(element_id="page", action="dialog", **fields).parameters()
        with self.assertRaises(ValueError):
            ElementAction(element_id="node", action="dialog", accept=True).parameters()
        for accept in ("false", 0, 1):
            with self.subTest(accept=accept), self.assertRaises(ValidationError):
                ElementAction(element_id="page", action="dialog", accept=accept)

    def test_mcp_schema_and_discard_warning(self):
        tool = next(t for t in tools_control.tool_list({"actions": ["write"]})
                    if t["name"] == "screen_element_action")
        self.assertIn("beforeunload accept=true", tool["description"])
        self.assertIn("discards unsaved changes", tool["description"])
        self.assertLessEqual(len(tool["description"]), 699)
        properties = tool["inputSchema"]["properties"]
        self.assertIn("dialog", properties["action"]["enum"])
        self.assertNotIn("default", properties["accept"])
        client = Mock(home="line")
        args = dict(element_id="page", action="dialog", accept=False, prompt_text="draft")
        tools_control.call(client, "screen_element_action", args, {"actions": ["write"]})
        self.assertEqual(client.request.call_args.args[2], args)


class DialogServer(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def dialog(self, **params):
        return await self.client.post("/api/conversations/alpha/screen-control/element-action",
            headers=self.machine("a"), json=dict(element_id="page", action="dialog", **params))

    async def test_old_helper_missing_accept_and_revoked_grant_send_nothing(self):
        await self.grant("a")
        self.device["chrome_dom"] = 4
        self.sent.clear()
        result = await self.dialog(accept=False)
        self.assertEqual(result.status_code, 409)
        self.assertIn("update the Partyline helper to use dialog", result.text)
        self.device["chrome_dom"] = 5
        self.assertEqual((await self.dialog()).status_code, 409)
        self.assertFalse(self.sent)
        await self.hub.window_grants.revoke("g1")
        self.sent.clear()
        result = await self.dialog(accept=True)
        self.assertGreaterEqual(result.status_code, 400)
        self.assertFalse(self.sent)

    async def test_dialog_bypasses_element_snapshot_but_spends_and_sends_exact_input(self):
        await self.grant("a")
        self.device["chrome_dom"] = 5
        self.sent.clear()
        with patch.object(self.hub.window_grants, "spend", wraps=self.hub.window_grants.spend) as spend, \
             patch.object(self.hub.elements, "action_target", side_effect=AssertionError("no tree needed")):
            result = await self.dialog(accept=False, prompt_text="Draft")
            self.assertEqual(result.status_code, 200, result.text)
            spend.assert_called_once()
        message = next(m for m in self.sent if m["type"] == "window_element_action")
        self.assertEqual(message["accept"], False)
        self.assertEqual(message["prompt_text"], "Draft")
        self.assertEqual(message["element_id"], "page")
        self.assertEqual(message["grant_id"], "g1")

    async def test_read_and_inspect_keep_dialog_metadata_and_action_reports_it(self):
        await self.grant("a")
        await self.read("a")
        reply = dict(source="cdp", page_dialog={"type": "beforeunload", "message": "Leave?"},
                     error="Page dialog is open; use dialog", dialog_hint="use dialog")
        async def answer(message):
            self.sent.append(message)
            self.hub.elements.receive(self.device, {"request_id": message["request_id"], **reply})
        self.device["socket"].send_json = answer
        result = await self.client.post("/api/conversations/alpha/screen-elements",
            params={"refresh": True}, headers=self.machine("a"))
        self.assertEqual(result.json()["page_dialog"], reply["page_dialog"])
        self.assertEqual(result.json()["window"], "g1")
        self.assertEqual(result.json()["window_title"], "Editor")
        result = await self.act("a")
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(result.json()["detail"]["page_dialog"], reply["page_dialog"])
