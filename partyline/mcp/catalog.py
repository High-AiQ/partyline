"""What a process is shown, and what it may call: two different sets.

Every `tools/list` used to carry every tool the attachment's capabilities allow,
about fifty schemas for a captain, and a client pays for them on every turn. Most
of them (Blender, render checks, 3D uploads, handover, screen control on clients
that never re-list) are for a rare errand. They stay callable, by name and
through the one `extras(op, args)` tool; `guide()` lists them with a line each and
`guide(topic=<tool>)` gives the full text and schema on request.
"""

from __future__ import annotations

from . import (
    tools_blender, tools_captain, tools_check, tools_control, tools_core, tools_handover,
    tools_resources, tools_tasks,
)
from .captain_schemas import ACK_HINT
from .client import ApiError
from .validation import validate_arguments
from .descriptions import one_line, slim_schema

# The order a name is looked up in; the first module serving it handles the call.
DISPATCH = (tools_blender, tools_check, tools_control, tools_handover, tools_resources, tools_tasks,
            tools_core, tools_captain)
# The order tools are shown in.
LISTING = (tools_core, tools_captain, tools_tasks, tools_resources, tools_handover, tools_control,
           tools_blender, tools_check)

# Reached through extras(op, args): rare errands, or tools a client cannot be given later.
EXTRAS_OPS = frozenset({
    "blender_request", "blender_exec", "blender_scene_info", "blender_render", "blender_screenshot",
    "blender_end", "render_check", "upload_3d_model", "upload_file",
    "offer_handover", "cancel_handover", "accept_handover", "complete_handover",
})
# Clients that never re-list cannot gain a screen tool when a share starts, so the
# whole control set is reached through extras there; the others list it while shared.
SCREEN_CONTROL = frozenset({
    "screen_element_action", "screen_control_request", "screen_click", "screen_move",
    "screen_drag", "screen_scroll", "screen_type", "screen_key",
})
SCREEN = SCREEN_CONTROL | {"screen_frame", "screen_elements"}
# Captain and task operations that stay listed; every other one runs as captain(op, args).
EVERYDAY = frozenset({
    "attach_worker", "detach_worker", "create_child", "accept", "ack_report", "list_presets", "reports",
    "create_task", "tasks", "message_task", "set_task_goal", "reopen_task",
    "env_gap", "blocked", "deliver", "request_review", "review_verdict", "waiting", "resume_work",
})
EXTRAS = "extras"
CAPTAIN = "captain"


def every_tool(state: dict) -> list[dict]:
    """Every tool this attachment may call right now, in full."""
    return [tool for module in LISTING for tool in module.tool_list(state)]


def door(name: str, state: dict) -> str | None:
    """The tool that runs ``name`` when it is not listed itself; None when it is listed."""
    if name in EXTRAS_OPS or (name in SCREEN_CONTROL and not state.get("dynamic_screen_tools")):
        return EXTRAS
    if name in (*tools_captain.OPERATIONS, *tools_tasks.OPERATIONS) and name not in EVERYDAY:
        return CAPTAIN
    if name == CAPTAIN and state.get("dynamic_screen_tools") and not tools_captain.is_lead(state):
        return "-"  # a client that re-lists gains it when appointed; nothing to run now
    return None


def _door_tool(tool: dict, hidden: list[str]) -> dict:
    schema = {**tool["inputSchema"], "properties": {"op": {"type": "string"}, "args": {"type": "object"}}}
    return {**tool, "inputSchema": schema, "description": (
        "Run any captain operation: captain(op, args). Not listed on their own: " + ", ".join(hidden)
        + ". guide(topic=<op>) gives the schema.")}


def _extras_tool(names: list[str]) -> dict:
    return {"name": EXTRAS, "description": (
        "Run a specialist tool that is not listed: extras(op, args). ops: " + ", ".join(names)
        + ". guide(topic=<op>) gives its text and schema."),
        "inputSchema": {"type": "object", "properties": {
            "op": {"type": "string"}, "args": {"type": "object"}},
            "required": ["op", "args"], "additionalProperties": False}}


def slim(tool: dict) -> dict:
    """One line of description and no schema noise; the full text is in guide(topic=name)."""
    return {**tool, "description": one_line(tool["name"], tool["description"]),
            "inputSchema": slim_schema(tool["inputSchema"])}


def listed(state: dict) -> list[dict]:
    """The tools/list reply: the everyday tools, then the doors to the rest."""
    tools = every_tool(state)
    behind = {tool["name"]: door(tool["name"], state) for tool in tools}
    via = lambda which: [name for name, value in behind.items() if value == which]  # noqa: E731
    shown = []
    for tool in tools:
        if behind[tool["name"]] is not None:
            continue
        slimmed = slim(tool)
        shown.append(_door_tool(slimmed, via(CAPTAIN)) if tool["name"] == CAPTAIN and via(CAPTAIN)
                     else slimmed)
    return shown + ([_extras_tool(via(EXTRAS))] if via(EXTRAS) else [])


def owner(state: dict, name: str):
    """The module that serves ``name`` for this state, or None."""
    return next((module for module in DISPATCH
                 if any(tool["name"] == name for tool in module.tool_list(state))), None)


def dispatch(client, name: str, args: dict, state: dict):
    """Run one tool, listed or not. Refused with the old messages when it is not permitted."""
    if name == EXTRAS:
        if set(args) != {"op", "args"} or not isinstance(args["op"], str) \
                or not isinstance(args["args"], dict):
            raise ValueError("extras requires exactly op and args (an object)")
        if door(args["op"], state) != EXTRAS:
            raise ValueError("extras runs only the specialist ops its description lists")
        return dispatch(client, args["op"], args["args"], state)
    module = owner(state, name)
    if module is None:
        if name in SCREEN and state.get("dynamic_screen_tools"):
            raise ApiError("no screen shared with you")
        raise ValueError("tool is not currently available to this attachment")
    if module is tools_core:
        tool = next(item for item in tools_core.tool_list(state) if item["name"] == name)
        validate_arguments(tool["inputSchema"], args, ACK_HINT if name == "reports" else "")
    return module.call(client, name, args, state)


def guide_entry(state: dict, name: str) -> dict | None:
    """The full text and schema of one callable tool, for guide(topic=name)."""
    tool = next((tool for tool in every_tool(state) if tool["name"] == name), None)
    if tool is None:
        return None
    way = door(name, state)
    return {"name": name, "description": tool["description"], "inputSchema": tool["inputSchema"],
            "call": name if way is None else f"{way}(op={name!r}, args={{...}})"}


def guide_index(state: dict) -> dict:
    """guide() with no arguments: every callable tool, one line each; no schemas."""
    rows = []
    for tool in every_tool(state):
        way = door(tool["name"], state)
        rows.append({"name": tool["name"], "description": one_line(tool["name"], tool["description"]),
                     **({"via": way} if way in (EXTRAS, CAPTAIN) else {})})
    return {"title": "Partyline tools", "tools": rows,
            "more": "guide(topic=<tool>) gives one tool's full text and schema; "
                    "guide(category=..., topic=...) reads the docs."}
