"""Explicit captain operation handlers; every route is fixed in this module."""

from urllib.parse import quote

from .client import ApiError
from .captain_schemas import OPERATIONS

_MAX_WRITE_SET_GRANTS = 50


def _path(conv, tail):
    return f"/api/conversations/{quote(conv, safe='')}/{tail}"


def _target(client, home, conv, actions):
    if not isinstance(conv, str) or not conv:
        raise ValueError("conv_id is required")
    state = home if conv == client.home else client.capabilities(conv)
    if not set(actions).issubset(set(state.get("actions", []))):
        raise ApiError("captain is not authorized for that target line")
    return state


def _check_lead(state):
    if state.get("kind") != "machine" or state.get("role") != "lead" or not state.get("is_lead"):
        raise ApiError("current attachment is not a line captain")


def execute(client, op, args, state):
    """Validate arguments and call only a named, hard-coded Partyline route."""
    if op not in OPERATIONS:
        raise ValueError("unknown captain operation")
    _check_lead(state)
    if op == "list_presets":
        return client.request("GET", "/api/presets")
    if op == "docs_read":
        path = "/api/docs"
        category, topic = args.get("category"), args.get("topic")
        if topic and not category:
            raise ValueError("category is required when topic is set")
        if category:
            path += "/" + quote(category, safe="")
        if topic:
            path += "/" + quote(topic, safe="")
        return client.request("GET", path)
    if op == "reports":
        return _reports(client, state, args)
    if op == "detach_worker":
        conv = args.get("conv_id")
        target = _target(client, state, conv, ("close",))
        _check_lead(state)
        if not target:
            raise ApiError("captain is not authorized for that target line")
        att = args.get("attachment_id")
        if not isinstance(att, str) or not att:
            raise ValueError("attachment_id is required")
        detail = client.request("GET", f"/api/conversations/{quote(conv, safe='')}")
        rows = detail.get("attachments", []) if isinstance(detail, dict) else []
        if not any(isinstance(row, dict) and row.get("id") == att for row in rows):
            raise ApiError("attachment is not on the authorized target line")
        return client.request("DELETE", f"/api/attachments/{quote(att, safe='')}")
    if op == "retire_child":
        conv = args.get("conv_id")
        children = client.request("GET", _path(client.home, "children"))
        if not any(isinstance(row, dict) and row.get("id") == conv for row in children):
            raise ApiError("retire_child only accepts a direct child line")
        _target(client, state, conv, ("archive",))
        query = "?stop_processes=true" if args.get("stop_processes") is True else ""
        return client.request("DELETE", f"/api/conversations/{quote(conv, safe='')}{query}")
    conv = args.get("conv_id")
    if op == "staffing":
        _target(client, state, conv, ("assign",))
        return client.request("GET", _path(conv, "staffing"))
    if op == "write_set_requests":
        _target(client, state, conv, ("read",))
        pending = client.request("GET", _path(conv, "write-set/request"))
        grants = client.request("GET", _path(conv, "write-set"))
        rows = grants if isinstance(grants, list) else []
        return {
            "request": pending.get("request") if isinstance(pending, dict) else None,
            "grants": [
                {key: row[key] for key in ("path", "granted_by", "granted_at", "docker_mode")
                 if key in row}
                for row in rows[:_MAX_WRITE_SET_GRANTS] if isinstance(row, dict)
            ],
            "grants_truncated": len(rows) > _MAX_WRITE_SET_GRANTS,
        }
    if op == "attach_worker":
        _target(client, state, conv, ("attach",))
        body = {key: args[key] for key in ("name", "adapter")}
        body["command"] = args.get("command", "")
        if args.get("allow_shared_branch") is True:
            body["allow_shared_branch"] = True
        preset_name = args.get("preset_name")
        if preset_name:
            presets = client.request("GET", "/api/presets")
            matches = [item for item in presets if item.get("name") == preset_name]
            if len(matches) != 1 or matches[0].get("adapter") != body["adapter"]:
                raise ValueError("preset_name must exactly match one preset with this adapter")
            if not args.get("command"):
                body["command"] = matches[0].get("command", "")
        return client.request("POST", _path(conv, "attachments"), body)
    paths = {
        "create_child": ("create_child", "POST", "children"),
        "appoint_lead": ("appoint_lead", "POST", "lead"),
        "accept": ("accept", "POST", "accept"),
        "review_worktree": ("write", "POST", "review-worktrees"),
        "request_write_set": ("write", "POST", "write-set"),
        "request_restart": ("assign", "POST", "restart-request"),
        "process_overview": ("read", "GET", "process-overview"),
        "ack_report": ("read_reports", "POST", f"reports/{args.get('report_id')}/ack"),
        "set_goal": ("assign", "PUT", "goal"),
        "set_gates": ("assign", "PUT", "gates"),
    }
    if op == "decide_write_set":
        return _decide_write_set(client, state, args)
    action, method, tail = paths[op]
    _target(client, state, conv, (action,))
    body = _body(op, args)
    return client.request(method, _path(conv, tail), body)


def _body(op, args):
    if op == "create_child":
        return {key: args[key] for key in ("name", "goal", "topic", "base", "repository")
                if key in args}
    if op == "appoint_lead":
        return {"attachment_id": args["attachment_id"] or None}
    if op == "accept":
        return {key: args[key] for key in ("sha", "allow_descendant", "findings", "run_gates")
                if key in args}
    if op == "review_worktree":
        return {key: args[key] for key in ("sha", "repository") if key in args}
    if op == "request_write_set":
        return {"path": args["path"]}
    if op == "request_restart":
        return {key: args[key] for key in ("reason", "confirm_no_deploy") if key in args}
    if op == "ack_report":
        return {"revision": args["revision"]}
    if op == "set_goal":
        return {"goal": args["goal"]}
    if op == "set_gates":
        return {key: args[key] for key in ("commands", "timeout_s") if key in args}
    return None


def _decide_write_set(client, state, args):
    conv, req, decision = args.get("conv_id"), args.get("request_id"), args.get("decision")
    _target(client, state, conv, ("read",))
    base = _path(conv, f"write-set/request/{quote(str(req), safe='')}")
    if decision == "approve":
        return client.request("POST", base + "/approve", {})
    if decision == "deny":
        reason = args.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required to deny a write-set request")
        return client.request("POST", base + "/deny", {"reason": reason})
    if decision == "withdraw":
        if state.get("attachment_id") != client.connection.get("attachment_id"):
            raise ApiError("only the requesting attachment may withdraw")
        return client.request("POST", base + "/withdraw")
    raise ValueError("decision must be approve, deny, or withdraw; decline is person-only")


def _reports(client, state, args):
    operation = args["operation"]
    actions = set(state.get("actions", []))
    if operation == "list":
        if "read_reports" not in actions:
            raise ApiError("current attachment cannot read child reports")
        return client.request("GET", _path(client.home, "reports"))
    if operation != "post":
        raise ValueError("reports operation must be list or post")
    notify = bool(args.get("notify", False))
    required = "notify" if notify else "report"
    if required not in actions:
        raise ApiError("current attachment cannot post that report")
    body = args.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("report body is required")
    if len(body) > 2000:
        raise ValueError("report body is capped at 2000 characters")
    return client.request("POST", _path(client.home, "reports"),
                          {"body": body, "notify": notify})
