"""The hook intake, as a pure function of the payload.

Turn boundaries are read from the *harness's* event name. Nothing an agent
can write into a chat message reaches this decision — which is the whole
point, and the reason it is a function that can be enumerated in a test.
"""

import unittest

from partyline.adapter_capabilities import adapter_completion
from partyline.adapters import ADAPTER_METADATA
from partyline.bind import BindConfig
from partyline.hook_routes import hook_url, turn_boundary


class TurnBoundaryTest(unittest.TestCase):
    def test_the_paired_harness_events_are_the_only_boundaries(self):
        self.assertEqual(turn_boundary({"hookEventName": "UserPromptSubmit"}), "began")
        self.assertEqual(turn_boundary({"hookEventName": "Stop"}), "ended")
        self.assertEqual(turn_boundary({"hook_event_name": "Stop"}), "ended")

    def test_nothing_else_is_a_boundary(self):
        for payload in (
            {"hookEventName": "SubagentStop"},
            {"hookEventName": "Notification"},
            {"hookEventName": ""},
            {"hookEventName": None},
            {"hookEventName": {"nested": "Stop"}},
            {"message": "Stop"},
            {},
            None,
            "Stop",
            ["Stop"],
        ):
            self.assertIsNone(turn_boundary(payload), payload)


class CapabilityTest(unittest.TestCase):
    """An adapter is trusted with a receipt only when its manifest says so."""

    def setUp(self):
        self.saved = dict(ADAPTER_METADATA)
        self.addCleanup(lambda: (ADAPTER_METADATA.clear(), ADAPTER_METADATA.update(self.saved)))

    def register(self, metadata):
        ADAPTER_METADATA["probe"] = {"id": "probe", **metadata}

    def test_only_an_explicit_receipt_capability_counts(self):
        self.register({"capabilities": {"turn_end": "receipt"}})
        self.assertEqual(adapter_completion("probe"), "receipt")

        for metadata in (
            {},
            {"capabilities": {}},
            {"capabilities": {"resume": True}},
            {"capabilities": {"turn_end": "quiescence"}},
            {"capabilities": {"turn_end": True}},
            {"capabilities": ["turn_end"]},
        ):
            self.register(metadata)
            self.assertEqual(adapter_completion("probe"), "none", metadata)

    def test_an_unknown_adapter_is_never_trusted_with_a_receipt(self):
        self.assertEqual(adapter_completion("no-such-adapter"), "none")


class HookUrlTest(unittest.TestCase):
    def test_the_url_carries_the_token(self):
        self.assertEqual(
            hook_url("att", BindConfig("10.0.0.1", 8643), "tok"),
            "http://10.0.0.1:8643/api/hooks/att/tok",
        )

    def test_an_ipv6_host_is_bracketed(self):
        self.assertEqual(
            hook_url("att", BindConfig("::1", 8643), "tok"),
            "http://[::1]:8643/api/hooks/att/tok",
        )


if __name__ == "__main__":
    unittest.main()
