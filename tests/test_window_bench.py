"""CI-safe scoring tests; the interactive window runner itself is never invoked here."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.window_bench import element_id, main, write_results
from scripts.window_bench_logic import (
    ax_observation,
    confirms_refusal,
    estimate_tokens,
    image_tiers_in,
    percentile,
    response_cost,
    verify_response,
)


FAKES = json.loads((Path(__file__).parent / "fixtures/window_bench_responses.json").read_text())


class WindowBenchScoringTests(unittest.TestCase):
    def test_verification_uses_trusted_event_and_value_not_action_claim(self):
        result = verify_response(FAKES["verified"], "event", "target", "bench text")
        self.assertTrue(result["success"])
        self.assertEqual(result["evidence"]["events"][0]["type"], "input")

    def test_refusal_requires_explicit_action_refusal_and_no_trusted_event(self):
        refused = FAKES["refused"]
        self.assertFalse(verify_response(refused, "refused", "target")["success"])
        self.assertTrue(verify_response(
            refused, "refused", "target",
            action_refused=confirms_refusal(refused["action_response"]),
        )["success"])
        self.assertFalse(verify_response(FAKES["verified"], "refused", "target",
                                         action_refused=True)["success"])
        closed_host_click = {"observation": {"events": [
            {"trusted": True, "type": "click", "target": "CLOSED-TARGET"}],
            "covered_or_closed": True}}
        self.assertFalse(verify_response(closed_host_click, "refused", "target",
                                         action_refused=True)["success"])
        self.assertFalse(verify_response(FAKES["untrusted_claim"], "refused", "target",
                                        action_refused=confirms_refusal(
                                            FAKES["untrusted_claim"]["action_response"]))["success"])

    def test_only_explicit_refusal_responses_count(self):
        self.assertTrue(confirms_refusal({"status": "failed", "error": "element is covered"}))
        self.assertTrue(confirms_refusal("the computer refused the action"))
        self.assertFalse(confirms_refusal({"status": "failed", "error": "could not refresh"}))
        self.assertFalse(confirms_refusal({"status": "unconfirmed", "note": "may have run"}))

    def test_percentiles_cover_small_and_empty_samples(self):
        self.assertIsNone(percentile([], .5))
        self.assertEqual(percentile([8.1, 4.9, 3.4], .5), 4.9)
        self.assertEqual(percentile([1, 2, 3, 4, 5], .95), 5)

    def test_response_cost_counts_json_bytes_and_image_tiers(self):
        cost = response_cost({"text": "abcd"}, ["thumb", "slim"])
        self.assertEqual(cost["response_bytes"], len(b'{"text":"abcd"}'))
        self.assertEqual(cost["estimated_tokens"], cost["response_bytes"] // 4 + 405)
        self.assertEqual(estimate_tokens(400, ["thumb"]), 185)

    def test_ax_verification_parses_visible_event_log_and_state(self):
        observation = ax_observation(FAKES["ax_log"])
        result = verify_response({"observation": observation}, "event", "target", "bench text")
        self.assertEqual(observation["source"], "uia")
        self.assertTrue(result["success"])

    def test_image_tier_estimates_follow_returned_variants(self):
        self.assertEqual(image_tiers_in(FAKES["image_response"]), ["slim", "thumb"])


class WindowBenchCliTests(unittest.TestCase):
    def test_consent_flag_is_mandatory_before_running(self):
        with patch("sys.argv", ["window_bench.py", "--base-url", "https://bench.example",
                                "--window", "granted", "--transport", "uia", "--helper-version", "1.4.1",
                                "--cross-origin-url", "https://other.example"]):
            with self.assertRaises(SystemExit) as exit_info:
                main()
        self.assertEqual(exit_info.exception.code, 2)

    def test_element_id_reads_recorded_ax_line_format_and_disambiguates_by_name(self):
        sample = FAKES["element_lines"]
        self.assertEqual(element_id(sample, "Text input"), "edit-17")
        self.assertEqual(element_id(sample, "Save"), "button-22")
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            element_id(sample, "Missing")

    def test_write_results_emits_json_and_markdown_summary(self):
        result = {"transport": "uia", "helper_version": "1.4.1", "totals": {
            "verified": 1, "failed": 0, "manual_verified": 0, "manual_required": 0,
            "response_bytes": 100, "estimated_tokens": 25},
            "latency_ms": {"p50": 10, "p95": 10}, "latency_ms_by_action": {"invoke": {"p50": 10, "p95": 10}},
            "steps": [{"scenario": "button", "status": "verified", "wall_ms": 10,
                       "response_bytes": 100, "estimated_tokens": 25}]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            write_results(result, output)
            self.assertEqual(json.loads(output.read_text()), result)
            summary = output.with_suffix(".md").read_text()
            self.assertIn("Action latency p50/p95: 10 / 10 ms", summary)
            self.assertIn("| button | verified | 10 | 100 | 25 |", summary)


if __name__ == "__main__":
    unittest.main()
