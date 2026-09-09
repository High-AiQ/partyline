"""The `immediate_mentions` capability, Grok's host preflight, and Antigravity.

The contract under test is narrow and worth stating: *supported* is a claim an
adapter package makes, *effective* is whether that claim holds on this host.
Nothing here writes a user's configuration, and nothing here runs a vendor CLI.
"""

import tempfile
import unittest
from pathlib import Path

from partyline.adapter_capabilities import (
    ImmediateMentions,
    adapter_supports_immediate_mentions,
    immediate_mentions,
)
from partyline.adapters import ADAPTERS, ADAPTER_METADATA
from partyline.adapters.bundled.grok.steering import (
    QUEUE,
    STEER,
    grok_home,
    immediate_mentions_preflight,
    read_steering,
)


class GrokHome(unittest.TestCase):
    """A throwaway `$GROK_HOME` with `[ui] follow_up_behavior` in a chosen state."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.home = Path(self.directory.name)
        (self.home / ".grok").mkdir()
        self.env = {"HOME": str(self.home)}

    def tearDown(self):
        self.directory.cleanup()

    @property
    def config(self) -> Path:
        return self.home / ".grok" / "config.toml"

    def write(self, text: str) -> None:
        self.config.write_text(text)


class CapabilityDeclarationTest(unittest.TestCase):
    def test_only_an_explicit_true_claims_the_capability(self):
        self.assertTrue(adapter_supports_immediate_mentions("grok"))
        for kind in ("claude", "codex", "raw", "opencode", "antigravity"):
            with self.subTest(kind=kind):
                self.assertFalse(adapter_supports_immediate_mentions(kind))

    def test_an_unknown_adapter_does_not_claim_it(self):
        self.assertFalse(adapter_supports_immediate_mentions("nonesuch"))

    def test_a_truthy_non_true_value_is_not_a_claim(self):
        # A manifest is data from an imported package. "yes", 1, and a nested
        # table are all truthy in Python and none of them is the declaration.
        original = ADAPTER_METADATA["raw"].get("capabilities")
        try:
            for value in ("yes", 1, {"steer": True}, None):
                with self.subTest(value=value):
                    ADAPTER_METADATA["raw"]["capabilities"] = {"immediate_mentions": value}
                    self.assertFalse(adapter_supports_immediate_mentions("raw"))
        finally:
            ADAPTER_METADATA["raw"]["capabilities"] = original

    def test_capabilities_that_are_not_a_table_do_not_crash_the_check(self):
        original = ADAPTER_METADATA["raw"].get("capabilities")
        try:
            ADAPTER_METADATA["raw"]["capabilities"] = ["immediate_mentions"]
            self.assertFalse(adapter_supports_immediate_mentions("raw"))
        finally:
            ADAPTER_METADATA["raw"]["capabilities"] = original


class GrokSteeringPreflightTest(GrokHome):
    def test_steer_is_the_only_value_that_makes_it_effective(self):
        self.write('[ui]\nfollow_up_behavior = "steer"\n')

        steering = read_steering(self.env)

        self.assertEqual(steering.behavior, STEER)
        self.assertTrue(steering.steers)
        self.assertEqual(immediate_mentions_preflight(self.env)[0], True)

    def test_the_documented_default_is_queue(self):
        self.write('[ui]\nfollow_up_behavior = "queue"\n')

        self.assertEqual(read_steering(self.env).behavior, QUEUE)
        self.assertFalse(immediate_mentions_preflight(self.env)[0])

    def test_an_undocumented_value_keeps_queueing_rather_than_being_trusted(self):
        # Grok ignores an unrecognised value instead of refusing it, so a
        # plausible-looking spelling would otherwise let us advertise
        # immediacy the CLI is not providing.
        self.write('[ui]\nfollow_up_behavior = "interject"\n')

        effective, detail = immediate_mentions_preflight(self.env)

        self.assertFalse(effective)
        self.assertIn("not a documented value", detail)

    def test_an_absent_key_section_or_file_all_resolve_to_queue(self):
        cases = {
            "missing file": None,
            "no [ui] table": '[models]\ndefault = "grok-4.6"\n',
            "no key": "[ui]\nmax_thoughts_width = 120\n",
            "ui is not a table": 'ui = "nonsense"\n',
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                if text is None:
                    self.config.unlink(missing_ok=True)
                else:
                    self.write(text)
                self.assertFalse(immediate_mentions_preflight(self.env)[0])

    def test_malformed_toml_is_refused_rather_than_assumed_steering(self):
        self.write("[ui\nfollow_up_behavior =\n")

        effective, detail = immediate_mentions_preflight(self.env)

        self.assertFalse(effective)
        self.assertIn("could not be read", detail)

    def test_the_refusal_names_the_file_and_the_remedy(self):
        # An operator told only "not immediate" has to rediscover the setting,
        # the file it lives in, and that a running Grok will not reload it.
        self.write('[ui]\nfollow_up_behavior = "queue"\n')

        _, detail = immediate_mentions_preflight(self.env)

        self.assertIn(str(self.config), detail)
        self.assertIn('follow_up_behavior = "steer"', detail)
        self.assertIn("resume", detail)

    def test_grok_home_overrides_the_default_location(self):
        elsewhere = self.home / "custom-home"
        elsewhere.mkdir()
        (elsewhere / "config.toml").write_text('[ui]\nfollow_up_behavior = "steer"\n')
        env = {**self.env, "GROK_HOME": str(elsewhere)}

        self.assertEqual(grok_home(env), elsewhere)
        self.assertTrue(immediate_mentions_preflight(env)[0])
        # The default location is untouched and still says queue.
        self.assertFalse(immediate_mentions_preflight(self.env)[0])

    def test_a_blank_grok_home_falls_back_to_the_default(self):
        self.write('[ui]\nfollow_up_behavior = "steer"\n')

        self.assertTrue(immediate_mentions_preflight({**self.env, "GROK_HOME": "   "})[0])

    def test_the_preflight_never_creates_or_writes_anything(self):
        self.config.unlink(missing_ok=True)
        before = sorted(path.name for path in (self.home / ".grok").iterdir())

        immediate_mentions_preflight(self.env)
        self.write('[ui]\nfollow_up_behavior = "steer"\n')
        digest = self.config.read_bytes()
        immediate_mentions_preflight(self.env)

        self.assertEqual(before, [])
        self.assertEqual(self.config.read_bytes(), digest)


class ResolvedCapabilityTest(GrokHome):
    def test_grok_is_supported_but_only_effective_under_steer(self):
        self.write('[ui]\nfollow_up_behavior = "queue"\n')
        queued = immediate_mentions("grok", self.env)
        self.write('[ui]\nfollow_up_behavior = "steer"\n')
        steered = immediate_mentions("grok", self.env)

        self.assertEqual((queued.supported, queued.effective), (True, False))
        self.assertEqual((steered.supported, steered.effective), (True, True))

    def test_an_adapter_without_the_claim_is_never_effective(self):
        self.write('[ui]\nfollow_up_behavior = "steer"\n')

        resolved = immediate_mentions("claude", self.env)

        self.assertEqual(resolved, ImmediateMentions(False, False, resolved.detail))
        self.assertIn("does not support", resolved.detail)

    def test_a_claim_without_a_preflight_needs_no_host_prerequisite(self):
        # Not every harness will have a host setting to check. One that claims
        # support and publishes no preflight is effective on its word.
        original = ADAPTER_METADATA["raw"].get("capabilities")
        try:
            ADAPTER_METADATA["raw"]["capabilities"] = {"immediate_mentions": True}
            self.assertIsNone(
                getattr(ADAPTERS["raw"], "immediate_mentions_preflight", None)
            )

            resolved = immediate_mentions("raw", self.env)

            self.assertEqual((resolved.supported, resolved.effective), (True, True))
        finally:
            ADAPTER_METADATA["raw"]["capabilities"] = original

    def test_antigravity_stays_false_while_its_strategy_is_unreachable(self):
        """Antigravity queues mid-turn messages like Grok, but exposes no way to change it.

        1.1.27 carries the strategy internally
        (``MESSAGE_DELIVERY_STRATEGY_{UNSPECIFIED,WHEN_IDLE,NEXT_INVOCATION}``)
        with no flag, settings key, slash command, or changelog entry to select
        it. Its only mid-turn keys, ``Esc`` and ``Ctrl+C``, cancel the running
        operation, and this capability forbids reaching a turn by stopping it.

        This test exists so that turning the claim on requires deleting it, and
        therefore requires saying which mechanism replaced the missing one.
        """
        resolved = immediate_mentions("antigravity", self.env)

        self.assertFalse(resolved.supported)
        self.assertFalse(resolved.effective)
        self.assertIsNone(
            getattr(ADAPTERS["antigravity"], "immediate_mentions_preflight", None),
            "a permanently false preflight is dead code; absence already means false",
        )

    def test_an_unknown_adapter_resolves_to_nothing_rather_than_raising(self):
        resolved = immediate_mentions("nonesuch", self.env)

        self.assertEqual((resolved.supported, resolved.effective), (False, False))


if __name__ == "__main__":
    unittest.main()
