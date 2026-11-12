"""Core MCP operations that read or write a line's notes, goal, reports and identity."""
from urllib.parse import quote

from .client import ApiError
from .pages import live_children
from . import tools_captain


def _target(client, home_state, conv_id, allowed):
    conv_id = conv_id or client.home
    state = home_state if conv_id == client.home else client.capabilities(conv_id)
    actions = set(state.get("actions", []))
    if not any(action in actions for action in allowed):
        raise ApiError("current attachment is not authorized for that line operation")
    return conv_id, state
def _whoami(client, state):
    conv = client.home
    detail = client.request("GET", f"/api/conversations/{quote(conv, safe='')}")
    line = detail.get("conversation", {}) if isinstance(detail, dict) else {}
    members = [{key: item.get(key) for key in ("id", "name", "status", "is_lead", "adapter")}
               for item in detail.get("attachments", []) if isinstance(item, dict)]
    children, retired = live_children(
        client.request("GET", f"/api/conversations/{quote(conv, safe='')}/children"))
    return {"identity": client.connection["handle"], "attachment_id": client.connection["attachment_id"],
            "line": {"id": conv, "name": line.get("name"), "topic": line.get("topic")},
            "role": state.get("role"), "capabilities": state.get("actions", []),
            "members": members, "parent_id": state.get("parent_id"),
            "children": children, "retired_children": retired}


def _notes(client, state, args):
    scope, operation = args["scope"], args["operation"]
    if scope not in {"line", "tree", "attachment"} or operation not in {"get", "set"}:
        raise ValueError("notes requires a valid operation and scope")
    conv, target = _target(client, state, args.get("conv_id"), ("read",))
    if scope == "attachment" and conv != client.home:
        raise ValueError("attachment notes are only available on your own line")
    query = f"scope={quote(scope, safe='')}"
    path = f"/api/conversations/{quote(conv, safe='')}/notes?{query}"
    if scope == "attachment":
        path += "&attachment_id=" + quote(client.connection["attachment_id"], safe="")
    if operation == "get":
        return client.request("GET", path)
    if scope != "attachment" and "assign" not in set(target.get("actions", [])):
        raise ApiError("only a captain can update line or tree notes")
    notes = args.get("notes")
    if not isinstance(notes, str) or len(notes) > 4000:
        raise ValueError("notes must be text no longer than 4000 characters")
    return client.request("PUT", path, {"notes": notes})


def _goal(client, state, args):
    if args["operation"] not in {"get", "set"}:
        raise ValueError("goal operation must be get or set")
    conv, target = _target(client, state, args.get("conv_id"), ("read",))
    path = f"/api/conversations/{quote(conv, safe='')}"
    if args["operation"] == "get":
        detail = client.request("GET", path)
        line = detail.get("conversation", {}) if isinstance(detail, dict) else {}
        return {key: line.get(key) for key in ("id", "name", "topic", "goal")}
    if "assign" not in set(target.get("actions", [])):
        raise ApiError("current attachment cannot set this line's goal")
    goal = args.get("goal")
    if not isinstance(goal, str) or len(goal) > 3000:
        raise ValueError("goal must be text no longer than 3000 characters")
    return client.request("PUT", path + "/goal", {"goal": goal})


def _reports(client, state, args):
    return tools_captain.captain_ops.reports(client, state, args)
