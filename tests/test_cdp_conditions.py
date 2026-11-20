"""Read-only CDP form conditions never focus or dispatch input."""
import unittest
from unittest.mock import AsyncMock

from tests.cdp_fakes import Fixture


class ConditionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.snapshot = await self.f.read()
        self.page = await self.f.chrome.page(self.f.access)
        self.page.quiet.wait = AsyncMock(return_value="quiet")
        self.select = self.snapshot["elements"][2]["id"]

    async def probe(self, action="select", value="New"):
        return await self.f.chrome.action(self.f.access, {
            "type": "window_element_condition", "action": action,
            "element_id": self.select, "value": value,
        })

    def assert_no_input(self):
        self.assertFalse(any(message["method"].startswith("Input.") or message["method"] == "DOM.focus"
                             for message in self.f.socket.calls))

    async def test_ready_missing_and_ambiguous_options_are_observations_without_input(self):
        result = await self.probe()
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["condition"]["ready"])
        result = await self.probe(value="missing")
        self.assertFalse(result["condition"]["ready"])
        self.assertNotIn("ambiguous", result["condition"])
        self.f.socket.options.append(dict(label="New", value="duplicate"))
        result = await self.probe()
        self.assertFalse(result["condition"]["ready"])
        self.assertTrue(result["condition"]["ambiguous"])
        self.assert_no_input()

    async def test_uia_source_never_routes_a_condition_into_the_write_fallback(self):
        self.f.chrome.sources[self.f.access] = "uia"
        self.f.access.elements[self.select] = {"id": self.select}
        result = await self.probe()
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["condition"]["ready"])
        self.assert_no_input()

    async def test_disabled_readonly_and_replaced_targets_cannot_be_verified_or_act(self):
        self.f.socket.states[3]["aria_disabled"] = True
        result = await self.probe()
        self.assertFalse(result["condition"]["ready"])
        self.assertIn("disabled", result["condition"]["error"])
        self.f.socket.states[3].update(tag="INPUT", aria_disabled=False, readonly=True)
        result = await self.probe(action="set_value", value="text")
        self.assertFalse(result["condition"]["ready"])
        self.f.socket.states.pop(3)
        result = await self.probe(action="set_value", value="text")
        self.assertEqual(("failed", "target_changed"), (result["status"], result["reason"]))
        self.assert_no_input()


if __name__ == "__main__":
    unittest.main()
