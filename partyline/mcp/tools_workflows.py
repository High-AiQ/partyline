"""Specialist workflow calls using the attachment's usual authenticated line routes."""

from urllib.parse import quote

from .validation import validate_arguments

PREFIX = "screen_workflow_"
START = PREFIX + "start"
OPERATIONS = {
    "list": ("List workflow definitions, approval and accessible runs for this line.", {}, ()),
    "show": (
        "Show a workflow's exact revision, parameters, and action plan.",
        {"workflow": {"type": "string"}},
        ("workflow",),
    ),
    "start": (
        "Start an approved workflow on an existing window grant ID. Progress comes to the line.",
        {
            "workflow": {"type": "string"},
            "window": {"type": "string"},
            "parameters": {"type": "object", "additionalProperties": True},
            "client_key": {"type": "string"},
        },
        ("workflow", "window", "parameters", "client_key"),
    ),
    "resume": (
        "Resume an approved workflow at its first unverified action, using the original parameters.",
        {
            "run_id": {"type": "string"},
            "parameters": {"type": "object", "additionalProperties": True},
        },
        ("run_id", "parameters"),
    ),
    "status": (
        "Read a run's state. Its starter or latest resuming process can query ended runs.",
        {"run_id": {"type": "string"}},
        ("run_id",),
    ),
    "stop": (
        "Stop a workflow and gate further input. Repeated stop requests are safe.",
        {"run_id": {"type": "string"}},
        ("run_id",),
    ),
}
NAMES = frozenset(PREFIX + op for op in OPERATIONS)


def tool_list(state):
    if state.get("kind") != "machine":
        return []
    return [
        {
            "name": PREFIX + op,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": props,
                "required": list(required),
                "additionalProperties": False,
            },
        }
        for op, (description, props, required) in OPERATIONS.items()
        if op not in ("start", "resume", "stop")
        or (
            "write" in state.get("actions", ())
            and (op == "stop" or state.get("screen_windows") or not state.get("dynamic_screen_tools"))
        )
    ]


def call(client, name, args, state):
    schema = next(tool["inputSchema"] for tool in tool_list(state) if tool["name"] == name)
    validate_arguments(schema, args)
    base = f"/api/conversations/{quote(client.home, safe='')}/screen-workflows"
    op = name.removeprefix(PREFIX)
    if op == "list":
        return {**client.request("GET", base), **client.request("GET", base + "/runs")}
    if op == "show":
        return client.request("GET", base + "/definitions/" + quote(args["workflow"], safe=""))
    if op == "start":
        return client.request("POST", base + "/runs", args)
    path = base + "/runs/" + quote(args["run_id"], safe="")
    if op == "resume":
        return client.request("POST", path + "/resume", {"parameters": args["parameters"]})
    return client.request("POST", path + "/stop") if op == "stop" else client.request("GET", path)
