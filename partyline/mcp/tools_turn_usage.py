"""Actual model usage per tool, readable on plain lines as well as captain trees."""

from urllib.parse import urlencode

from .validation import validate_arguments

SCHEMA = {"type": "object", "properties": {
    "conv_id": {"type": "string", "description": "Your line or a descendant."},
    "since": {"type": "number", "minimum": 0, "description": "Unix timestamp."},
    "group": {"type": "string", "enum": ["tool", "sub_op"]},
    "include_descendants": {"type": "boolean"}}, "additionalProperties": False}


def tool_list(state):
    return [{"name": "turn_usage", "description": (
        "Summarize the model's actual token usage (input, cache, output) per tool and operation: the "
        "whole turns that called it, with median and p95, and per-line and per-process totals. Defaults "
        "to your line over the retained 30 days. A turn is charged in full to every tool it called; "
        "tool_usage shows the estimated size of each tool's result for comparison."),
        "inputSchema": SCHEMA}]


def fetch(client, args):
    """The one read both this op and tool_usage use: the turn summary for a line."""
    validate_arguments(SCHEMA, args)
    query = {"conv_id": client.home, **args}
    if "include_descendants" in query:
        query["include_descendants"] = str(query["include_descendants"]).lower()
    return client.request("GET", "/api/telemetry/turns/summary?" + urlencode(query))


def call(client, name, args, state):
    return fetch(client, args)
