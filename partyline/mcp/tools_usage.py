"""Tool estimates are available on plain lines as well as captain trees."""

from urllib.parse import urlencode

from .validation import validate_arguments


def tool_list(state):
    return [{"name": "tool_usage", "description": (
        "Summarize estimated MCP result tokens by tool and operation, sorted by total. "
        "Defaults to your line over the retained 30 days; optionally include its sublines. "
        "Estimates exclude model turns and tool inputs; unknown image costs are counted separately."),
        "inputSchema": {"type": "object", "properties": {
            "conv_id": {"type": "string", "description": "Your line or a descendant."},
            "since": {"type": "number", "minimum": 0, "description": "Unix timestamp."},
            "group": {"type": "string", "enum": ["tool", "sub_op"]},
            "include_descendants": {"type": "boolean"}}, "additionalProperties": False}}]


def call(client, name, args, state):
    validate_arguments(tool_list(state)[0]["inputSchema"], args)
    query = {"conv_id": client.home, **args}
    if "include_descendants" in query:
        query["include_descendants"] = str(query["include_descendants"]).lower()
    return client.request("GET", "/api/telemetry/tool-calls/summary?" + urlencode(query))
