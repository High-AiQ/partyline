"""The hook intake, as a named contract of the payload.

Turn boundaries are read from the harness event name after folding dialects.
An unseen name is a 422, not a dropped receipt — that silence is how Grok's
`stop` left every jack `working…`.
"""

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from partyline.adapter_capabilities import adapter_completion
from partyline.adapters import ADAPTER_METADATA
from partyline.bind import BindConfig
from partyline.hook_contracts import parse_hook_payload
from partyline.hook_routes import hook_url


FIXTURES = Path(__file__).parent / "fixtures" / "hooks"

# Captured-shape fixtures: one per dialect we have seen. A new harness that
# does not fold onto began/ended fails this table rather than a stuck badge.
DIALECT_FIXTURES = (
    ("claude_userpromptsubmit.json", "began"),
    ("claude_stop.json", "ended"),
    ("grok_user_prompt_submit.json", "began"),
    ("grok_stop.json", "ended"),
    ("grok_stop_cancelled.json", "ended"),
)


def boundary(body: object) -> str | None:
    return parse_hook_payload(body).turn_boundary()


class TurnBoundaryTest(unittest.TestCase):
    def test_the_paired_harness_events_are_the_only_boundaries(self):
        self.assertEqual(boundary({"hookEventName": "UserPromptSubmit"}), "began")
        self.assertEqual(boundary({"hookEventName": "Stop"}), "ended")
        self.assertEqual(boundary({"hook_event_name": "Stop"}), "ended")

    def test_grok_snake_case_payloads_bound_the_turn(self):
        """Grok's stdin uses `stop`, not the Claude config key `Stop`."""
        self.assertEqual(boundary({"hookEventName": "user_prompt_submit"}), "began")
        self.assertEqual(boundary({"hookEventName": "stop"}), "ended")
        self.assertEqual(boundary({"hookEventName": "stop_failure"}), "ended")
        self.assertEqual(boundary({"hookEventName": "stop_cancelled"}), "ended")
        self.assertEqual(boundary({"hookEventName": "StopFailure"}), "ended")
        self.assertEqual(boundary({"hookEventName": "StopCancelled"}), "ended")

    def test_known_non_boundaries_parse_and_do_not_end_a_turn(self):
        for payload in (
            {"hookEventName": "SubagentStop"},
            {"hookEventName": "subagent_stop"},
            {"hookEventName": "Notification"},
        ):
            self.assertIsNone(boundary(payload), payload)

    def test_an_unknown_event_is_a_validation_error_not_silence(self):
        with self.assertRaises(ValidationError) as caught:
            parse_hook_payload({"hookEventName": "PreToolUse"})
        self.assertIn("unrecognized hook event", str(caught.exception))
        self.assertIn("PreToolUse", str(caught.exception))

    def test_a_missing_event_name_is_a_validation_error(self):
        with self.assertRaises(ValidationError) as caught:
            parse_hook_payload({"message": "Permission needed"})
        self.assertIn("hookEventName", str(caught.exception))


class DialectFixtureTest(unittest.TestCase):
    def test_each_captured_harness_shape_maps_to_a_turn_boundary(self):
        for name, expected in DIALECT_FIXTURES:
            with self.subTest(name):
                body = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
                self.assertEqual(boundary(body), expected, name)


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
