import json
from pathlib import Path

from scripts.window_bench_logic import (
    ax_observation, estimate_tokens, image_tiers_in, percentile, response_cost, verify_response,
)


FAKES = json.loads((Path(__file__).parent / "fixtures/window_bench_responses.json").read_text())


def test_verification_uses_trusted_event_and_value_not_action_claim():
    result = verify_response(FAKES["verified"], "event", "target", "bench text")
    assert result["success"] is True
    assert result["evidence"]["events"][0]["type"] == "input"


def test_action_success_claim_cannot_verify_untrusted_event():
    result = verify_response(FAKES["untrusted_claim"], "refused", "target")
    assert result["success"] is True


def test_refusal_requires_no_trusted_event_and_overlay_evidence():
    assert verify_response(FAKES["refused"], "refused", "target")["success"] is True
    assert verify_response(FAKES["verified"], "refused", "target")["success"] is False


def test_percentiles_cover_small_and_empty_samples():
    assert percentile([], .5) is None
    assert percentile([8.1, 4.9, 3.4], .5) == 4.9
    assert percentile([1, 2, 3, 4, 5], .95) == 5


def test_response_cost_counts_json_bytes_and_image_tiers():
    cost = response_cost({"text": "abcd"}, ["thumb", "slim"])
    assert cost["response_bytes"] == len(b'{"text":"abcd"}')
    assert cost["estimated_tokens"] == cost["response_bytes"] // 4 + 405
    assert estimate_tokens(400, ["thumb"]) == 185


def test_ax_verification_parses_visible_event_log_and_state():
    observation = ax_observation(FAKES["ax_log"])
    result = verify_response({"observation": observation}, "event", "target", "bench text")
    assert observation["source"] == "uia"
    assert result["success"] is True


def test_image_tier_estimates_follow_returned_variants():
    assert image_tiers_in(FAKES["image_response"]) == ["slim", "thumb"]
