"""Explicit captain operation handlers; every route is fixed in this module."""

from urllib.parse import quote, urlencode

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
        return reports(client, state, args)
    if op == "detach_worker":
        conv = args.get("conv_id")
        _target(client, state, conv, ("close",))
        ref = args.get("attachment_id")
        if not isinstance(ref, str) or not ref:
            raise ValueError("attachment_id is required")
        rows = _attachment_rows(client, conv)
        att = _resolve_handle(rows, ref)
        if not any(row.get("id") == att for row in rows):
            raise ApiError("attachment is not on the authorized target line")
        return client.request("DELETE", f"/api/attachments/{quote(att, safe='')}")
    if op == "retirement_preview":
        conv = args.get("conv_id")
        _target(client, state, conv, ("archive",))
        query = "?include_children=true" if args.get("include_children") is True else ""
        return client.request("GET", _path(conv, "retirement-preview") + query)
    if op == "retire_child":
        conv = args.get("conv_id")
        children = client.request("GET", _path(client.home, "children"))
        if (state.get("parent_id", "unknown") is not None
                and not any(isinstance(row, dict) and row.get("id") == conv for row in children)):
            raise ApiError("retire_child only accepts a direct child line")
        _target(client, state, conv, ("archive",))
        params = {key: "true" for key in
                  ("stop_processes", "clear_goal", "include_children", "discard", "force_discard")
                  if args.get(key) is True}
        if args.get("preview_token"):
            params["preview_token"] = args["preview_token"]
        query = "?" + urlencode(params) if params else ""
        return client.request("DELETE", f"/api/conversations/{quote(conv, safe='')}{query}")
    conv = args.get("conv_id")
    if op == "ack_report" and conv != client.home:
        # Reports a captain reads and acks live on its own line — read_reports
        # is granted only there — so a child line's id is only ever an alias
        # for it: prove the caller captains that child, then resolve to home.
        _target(client, state, conv, ("close",))
        conv = client.home
    if op == "resources":
        _target(client, state, conv, ("assign",))
        return client.request("POST", _path(conv, "resources"),
                              {key: args[key] for key in ("operation", "name") if key in args})
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
        if "counts_toward_total" in args:
            body["counts_toward_total"] = args["counts_toward_total"]
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
        "share_ref": ("assign", "POST", "task/share-ref"),
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
    if op == "appoint_lead" and args.get("attachment_id"):
        args = {**args, "attachment_id": _resolve_handle(_attachment_rows(client, conv),
                                                          args["attachment_id"])}
    body = _body(op, args)
    return client.request(method, _path(conv, tail), body)


_HANDLE_STATUSES = ("starting", "running", "idle")


def _attachment_rows(client, conv):
    """The attachments on one target line, as the server lists them."""
    detail = client.request("GET", f"/api/conversations/{quote(conv, safe='')}")
    rows = detail.get("attachments", []) if isinstance(detail, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _resolve_handle(rows, ref):
    """An attachment id, or a process handle such as ``impl-48da9d`` naming a live row.

    An id, or a handle no live row carries, comes back unchanged for the caller to judge.
    """
    if any(row.get("id") == ref for row in rows):
        return ref
    named = [row["id"] for row in rows
             if row.get("name") == ref and row.get("status") in _HANDLE_STATUSES]
    if len(named) > 1:
        raise ApiError(f"handle {ref} names {len(named)} live attachments on that line; "
                       "pass an attachment id")
    return named[0] if named else ref


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
    if op == "share_ref":
        return {key: args[key] for key in ("ref_or_sha", "name", "repository", "replace")
                if key in args}
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


def reports(client, state, args):
    operation = args["operation"]
    actions = set(state.get("actions", []))
    if operation in ("list", "get"):
        if "read_reports" not in actions:
            raise ApiError("current attachment cannot read child reports")
        if operation == "get":
            report_id = args.get("report_id")
            if not isinstance(report_id, int) or isinstance(report_id, bool) or report_id < 1:
                raise ValueError("report_id is required for get")
            return client.request("GET", _path(client.home, f"reports/{report_id}"))
        query = {key: args[key] for key in ("limit", "before_id") if args.get(key) is not None}
        return client.request("GET", _path(client.home, "reports")
                              + ("?" + urlencode(query) if query else ""))
    if operation != "post":
        raise ValueError("reports operation must be list, get or post")
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
