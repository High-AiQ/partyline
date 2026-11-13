"""Capability-filtered captain tools and the fixed-operation dispatcher."""

from .captain_schemas import OPERATIONS, schema, validate
from . import captain_ops, tools_tasks

_ACTION = {
    "resources": "assign", "staffing": "assign", "attach_worker": "attach", "detach_worker": "close",
    "create_child": "create_child", "new_chapter": "chapter",
    "appoint_lead": "appoint_lead", "retire_child": "assign",
    "accept": "accept", "review_worktree": "write", "share_ref": "message_task",
    "request_write_set": "write",
    "decide_write_set": "read", "write_set_requests": "read",
    "request_restart": "assign", "process_overview": "read",
    "ack_report": "read_reports", "set_goal": "assign", "set_gates": "assign",
    "retirement_preview": "assign",
}


def is_lead(state):
    return (state.get("kind") == "machine" and state.get("role") == "lead"
            and state.get("is_lead") is True)


def permitted(state):
    if not is_lead(state):
        return ()
    actions = set(state.get("actions", []))
    return tuple(op for op in OPERATIONS if op in {"list_presets", "docs_read"}
                 or (op == "kernel_log" and state.get("parent_id", "unknown") is None)
                 or (op == "reports" and bool({"read_reports", "report", "notify"} & actions))
                 or _ACTION.get(op) in actions)


DOORS = {
    "captain": "captain(op, args) runs any captain or task operation that is not listed on its own "
               "(restart_implementer, restart_reviewer, set_goal, share_ref, retirement_preview, "
               "retire_child, process_overview, docs_read, ...). op is the operation name and args "
               "an object with that operation's arguments; the listed ops are in the captain "
               "tool's description, and guide(topic=<op>) gives one op's schema.",
    "extras": "extras(op, args) runs a specialist tool that is not listed (Blender, render_check, "
              "upload_3d_model, upload_file, the handover tools, and screen control on clients that "
              "never re-list): the op is the tool name, args its arguments; guide(topic=<op>) "
              "gives its text and schema.",
}


def guide(state):
    return {"doors": DOORS,
            "goal_decisions": [
                {"need": "New task",
                 "operation": "create_task(name, goal, implementer, review, mode=full|light|express)"},
                {"need": "Change active task goal", "operation": "set_task_goal(conv_id, goal)"},
                {"need": "New work on approved/done task", "operation": "reopen_task(conv_id, goal)"},
                {"need": "Sub-captain line", "operation": "create_child(parent_conv_id, name, goal); "
                              "later set_goal(child_conv_id, goal)"}],
            "goal_context": ("Task participants receive the goal in their joining pack and on wakes until "
                             "delivery is proven, then on goal change or restart. Live participants "
                             "receive a durable update message. "
                             "Ordinary workers get assignments from their captain, not captain goal framing. "
                             "Use the child's line id for task operations; never park briefs in /tmp files."),
            "operations": [{"name": name, "inputSchema": schema(name)}
                            for name in permitted(state)],
            "fallback": {"name": "captain", "inputSchema": {
                "type": "object", "properties": {
                    "op": {"type": "string", "enum": [*OPERATIONS, *tools_tasks.OPERATIONS]},
                    "args": {"type": "object"}}, "required": ["op", "args"],
                "additionalProperties": False}}}


def tool_list(state: dict) -> list[dict]:
    tools = [{"name": "captain",
              "description": "Run one fixed captain operation; availability is checked live.",
              "inputSchema": guide({"kind": "machine", "role": "implementer", "is_lead": False})[
                  "fallback"]["inputSchema"]}]
    for op in permitted(state):
        descriptions = {
            "create_child": "Create a child line; its captain requires Can manage a line checked.",
            "new_chapter": "Start a fresh line that continues your own line (same parent, folder, topic, "
                "goal, notes and captain style; nothing moves or is deleted). A person appoints its captain.",
            "attach_worker": "Staff an implementer with Fast implementer checked; "
                "for visual work prefer Reads images. Set staffing_role=captain for a sub-captain. "
                "For handover, attach on your own line with successor=true, "
                "wait 60 seconds, then use offer_handover to offer captainship.",
            "process_overview": "Inspect lines and live processes, including every task workspace's real and "
                "mirror tips. The mirror tip is where the worker's commits live until accept.",
            "retirement_preview": "Inspect bounded retirement evidence and obtain a principal-bound token. "
                "Lists dirty/untracked/ignored files, history, processes, goals, children and assets, "
                "and required_flags names every flag the retirement needs.",
            "retire_child": "Retire a child (root: any strict descendant). Defaults stay guarded. "
                "Root force_discard requires preview_token; captures recovery refs before discarding "
                "tracked/untracked files. Ignored files are lost. Explicit stop/clear/recursive flags apply.",
        }
        tools.append({"name": op, "description": descriptions.get(op, f"Authorized captain operation: {op}."),
                      "inputSchema": schema(op)})
    return tools


def call(client, name: str, args: dict, state: dict):
    if name == "captain":
        if set(args) != {"op", "args"}:
            raise ValueError("captain requires exactly op and args")
        op, operation_args = args.get("op"), args.get("args")
        if not isinstance(op, str) or op not in (*OPERATIONS, *tools_tasks.OPERATIONS):
            raise ValueError("unknown captain operation: the valid ops are listed in the captain tool's "
                             "description and in guide(topic=\"captain\")")
        if not isinstance(operation_args, dict):
            raise ValueError("captain args must be an object")
        if op in tools_tasks.OPERATIONS:
            # Task operations ride the always-listed dispatcher too: a Codex
            # root appointed after its first tools/list never re-lists, and
            # read source to find create_task (2026-10-23).
            return tools_tasks.call(client, op, operation_args, state)
    else:
        op, operation_args = name, args
        if op not in OPERATIONS:
            raise ValueError("unknown captain MCP tool")
    if not is_lead(state):
        from .client import ApiError
        raise ApiError("current attachment is not a line captain")
    if op not in permitted(state):
        raise ValueError("captain operation is not currently available")
    return captain_ops.execute(client, op, validate(op, operation_args), state)
