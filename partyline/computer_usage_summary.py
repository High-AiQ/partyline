"""Computer-use totals over existing response and tool telemetry; never writes."""

from collections import defaultdict
import json
import time

from .computer_usage_contracts import ComputerUseSummary
from .mcp.catalog import SCREEN
from .mcp.tools_control import ELEMENT_ACTION_PROPERTIES
from .turn_usage import RETENTION_SECONDS
from .turn_usage_summary import percentile

ACTIONS = frozenset({
    "screen_eval", "screen_element_action", "screen_click", "screen_move", "screen_drag", "screen_scroll",
    "screen_type", "screen_key", "screen_window_click", "screen_window_scroll", "screen_window_drag",
    "screen_window_type", "screen_window_key",
})
READS = frozenset({"screen_frame", "screen_elements", "screen_window_snapshot", "screen_window_look",
                   "screen_windows"})
ELEMENT_ACTIONS = frozenset(ELEMENT_ACTION_PROPERTIES["action"]["enum"])
_SCREEN_NAMES = tuple(sorted(SCREEN))
_SCREEN_MARKS = ",".join("?" for _ in _SCREEN_NAMES)
_COMPUTER_CALL = f"""(
    json_extract(metrics, '$.tool') IN ({_SCREEN_MARKS}) OR
    (json_extract(metrics, '$.tool') = 'extras' AND
     json_extract(metrics, '$.sub_op') IN ({_SCREEN_MARKS})) OR
    (json_extract(metrics, '$.tool') = 'get_media' AND
     json_extract(metrics, '$.media_source') = 'screen')
)"""
BASIS = (
    "Model tokens are counted once per computer-use response. Codex uses recorded screen calls between "
    "responses on the same attachment. Other adapters use tool labels. "
    "Actions and reads are screen calls; other_calls are control or attachment calls. Image tokens are "
    "estimates; unknown estimates are counted separately. Model time is recorded thinking time and tool time "
    "is screen-call latency. Action p50/p95 are nearest-rank intervals between consecutive action "
    "completions per process, including the intervening model and tool time and any pause. Errors include "
    "refused and failed calls; unconfirmed and legacy unknown outcomes are separate. Images include inline "
    "results and screen references delivered through get_media. Retained history is about 30 days; cost_usd "
    "stays null until a price table exists."
)


def _is_computer_response(labels) -> bool:
    for label in labels:
        tool, _, sub_op = label.partition(":")
        if tool in SCREEN or (tool == "extras" and (sub_op in SCREEN or sub_op in ELEMENT_ACTIONS)):
            return True
    return False


def _screen_name(metrics) -> str | None:
    tool, sub_op = metrics.get("tool"), metrics.get("sub_op")
    if tool in SCREEN:
        return tool
    if tool == "extras" and sub_op in SCREEN:
        return sub_op
    return None


def _computer_turns(db, line_ids, marks, since, retained_since):
    # Find the prior response even when it precedes the requested window. Use
    # (timestamp, id) order so tied responses cannot both claim the same call.
    rows = db._exec(
        f"""SELECT response.*, CASE WHEN response.adapter = 'codex' THEN EXISTS (
            SELECT 1 FROM tool_calls AS call
            WHERE call.attachment_id = response.attachment_id AND call.conv_id = response.conv_id
              AND call.timestamp BETWEEN MAX(?, COALESCE(previous.timestamp, 0)) AND response.timestamp
              AND call.timestamp IS NOT previous.timestamp
              AND {_COMPUTER_CALL}
        ) END AS has_screen_call
        FROM turn_usage AS response
        LEFT JOIN turn_usage AS previous ON previous.id = CASE WHEN response.adapter = 'codex' THEN (
            SELECT prior.id FROM turn_usage AS prior
            WHERE prior.attachment_id = response.attachment_id
              AND (prior.timestamp, prior.id) < (response.timestamp, response.id)
            ORDER BY prior.timestamp DESC, prior.id DESC LIMIT 1
        ) END
        WHERE response.conv_id IN ({marks}) AND response.timestamp >= ?""",
        (retained_since, *_SCREEN_NAMES, *_SCREEN_NAMES, *line_ids, since),
    ).fetchall()
    return [row for row in rows if (
        row["has_screen_call"] if row["adapter"] == "codex"
        else _is_computer_response(json.loads(row["calls"]))
    )]


def _action_intervals(calls) -> list[float]:
    grouped = defaultdict(list)
    for row, name in calls:
        if name in ACTIONS:
            grouped[row["attachment_id"]].append(row["timestamp"])
    intervals = []
    for timestamps in grouped.values():
        ordered = sorted(timestamps)
        pairs = zip(ordered, ordered[1:], strict=False)
        intervals.extend((later - earlier) * 1000 for earlier, later in pairs if later >= earlier)
    return intervals


def summary(db, conv_id, line_ids, since, include_descendants=False, *, now=None) -> ComputerUseSummary:
    now = time.time() if now is None else now
    retained_since = now - RETENTION_SECONDS
    since = max(since, retained_since)
    marks = ",".join("?" for _ in line_ids)
    turns = _computer_turns(db, line_ids, marks, since, retained_since)
    records = db._exec(
        f"SELECT * FROM tool_calls WHERE conv_id IN ({marks}) AND timestamp >= ? AND {_COMPUTER_CALL}",
        (*line_ids, since, *_SCREEN_NAMES, *_SCREEN_NAMES),
    ).fetchall()
    parsed = [(row, json.loads(row["metrics"])) for row in records]
    calls = [(row, name) for row, metrics in parsed if (name := _screen_name(metrics)) is not None]
    images = [image for _, metrics in parsed for image in metrics["images"]]
    intervals = _action_intervals(calls)
    return ComputerUseSummary(
        conv_id=conv_id, since=since, include_descendants=include_descendants, basis=BASIS,
        responses=len(turns), calls=len(calls),
        actions=sum(name in ACTIONS for _, name in calls), reads=sum(name in READS for _, name in calls),
        other_calls=sum(name not in ACTIONS | READS for _, name in calls),
        images=len(images), image_tokens=sum(image["estimated_tokens"] or 0 for image in images),
        images_with_unknown_tokens=sum(image["estimated_tokens"] is None for image in images),
        input_tokens=sum(row["input_tokens"] for row in turns),
        cache_read_tokens=sum(row["cache_read_tokens"] for row in turns),
        cache_write_tokens=sum(row["cache_write_tokens"] for row in turns),
        output_tokens=sum(row["output_tokens"] for row in turns),
        total_tokens=sum(row["total_tokens"] for row in turns),
        model_ms=sum(row["model_ms"] or 0 for row in turns),
        model_time_responses=sum(row["model_ms"] is not None for row in turns),
        tool_ms=sum(json.loads(row["metrics"])["latency_ms"] for row, _ in calls),
        action_intervals=len(intervals), p50_action_ms=percentile(intervals, .5) if intervals else None,
        p95_action_ms=percentile(intervals, .95) if intervals else None,
        errors=sum(metrics["is_error"] or metrics.get("outcome") == "failed"
                   for _, metrics in parsed if _screen_name(metrics)),
        unconfirmed=sum(metrics.get("outcome") == "unconfirmed"
                        for _, metrics in parsed if _screen_name(metrics)),
        outcome_unknown=sum(metrics.get("outcome", "unknown") == "unknown"
                            for _, metrics in parsed if _screen_name(metrics)),
    )
