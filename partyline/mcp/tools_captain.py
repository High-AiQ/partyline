"""Capability-filtered captain tools and the fixed-operation dispatcher."""

from .captain_schemas import OPERATIONS, schema, validate
from . import captain_ops

_ACTION = {
    "staffing": "assign", "attach_worker": "attach", "detach_worker": "close",
    "create_child": "create_child", "appoint_lead": "appoint_lead", "retire_child": "assign",
    "accept": "accept", "review_worktree": "write", "request_write_set": "write",
    "decide_write_set": "read", "write_set_requests": "read",
    "request_restart": "assign", "process_overview": "read",
    "ack_report": "read_reports", "set_goal": "assign", "set_gates": "assign",
}


def _lead(state):
    return (state.get("kind") == "machine" and state.get("role") == "lead"
            and state.get("is_lead") is True)


def permitted(state):
    if not _lead(state):
        return ()
    actions = set(state.get("actions", []))
    return tuple(op for op in OPERATIONS if op in {"list_presets", "docs_read"}
                 or _ACTION.get(op) in actions)


def guide(state):
    return {"operations": [{"name": name, "inputSchema": schema(name)}
                            for name in permitted(state)],
            "fallback": {"name": "captain", "inputSchema": {
                "type": "object", "properties": {
                    "op": {"type": "string", "enum": list(OPERATIONS)},
                    "args": {"type": "object"}}, "required": ["op", "args"],
                "additionalProperties": False}}}


def tool_list(state: dict) -> list[dict]:
    tools = [{"name": "captain",
              "description": "Run one fixed captain operation; availability is checked live.",
              "inputSchema": guide({"kind": "machine", "role": "implementer", "is_lead": False})[
                  "fallback"]["inputSchema"]}]
    for op in permitted(state):
        tools.append({"name": op, "description": f"Authorized captain operation: {op}.",
                      "inputSchema": schema(op)})
    return tools


def call(client, name: str, args: dict, state: dict):
    if name == "captain":
        if set(args) != {"op", "args"}:
            raise ValueError("captain requires exactly op and args")
        op, operation_args = args.get("op"), args.get("args")
        if not isinstance(op, str) or op not in OPERATIONS:
            raise ValueError("unknown captain operation")
        if not isinstance(operation_args, dict):
            raise ValueError("captain args must be an object")
    else:
        op, operation_args = name, args
        if op not in OPERATIONS:
            raise ValueError("unknown captain MCP tool")
    if not _lead(state):
        from .client import ApiError
        raise ApiError("current attachment is not a line captain")
    if op not in permitted(state):
        raise ValueError("captain operation is not currently available")
    return captain_ops.execute(client, op, validate(op, operation_args), state)
