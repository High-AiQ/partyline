"""Core, named MCP operations backed by fixed Partyline API routes."""

from urllib.parse import quote

from .client import ApiError, MAX_UPLOAD
from .uploads import validate_uploads
from .tools_media import multi_upload_tool
from . import tools_captain


def _schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {},
            "required": required or [], "additionalProperties": False}


def _prop(kind, description, **extra):
    return {"type": kind, "description": description, **extra}


def tool_list(state):
    actions = set(state.get("actions", []))
    tools = [
        {
            "name": "whoami",
            "description": "Show identity, role, line members, and permitted hierarchy.",
            "inputSchema": _schema(),
        },
        {
            "name": "guide",
            "description": "Read Partyline's on-demand endpoint and workflow guide.",
            "inputSchema": _schema({
                "category": _prop("string", "Optional guide category."),
                "topic": _prop("string", "Optional topic within the category."),
            }),
        },
    ]
    if "read" in actions:
        tools.extend([
            {
                "name": "read_messages",
                "description": "Read a bounded page, optionally around a message id.",
                "inputSchema": _schema({
                    "conv_id": _prop("string", "Visible line; defaults to your line."),
                    "after_id": _prop("integer", "Return newer messages after this id."),
                    "before_id": _prop("integer", "Return older messages before this id."),
                    "around_id": _prop("integer", "Return messages surrounding this id."),
                    "limit": _prop("integer", "Page size, 1 to 50.", minimum=1, maximum=50),
                }),
            },
            {
                "name": "notes",
                "description": "Read or update line, tree, or your own attachment notes.",
                "inputSchema": _schema({
                    "operation": _prop("string", "get or set.", enum=["get", "set"]),
                    "scope": _prop("string", "line, tree, or attachment.",
                                   enum=["line", "tree", "attachment"]),
                    "conv_id": _prop("string", "Visible line; defaults to your line."),
                    "notes": _prop("string", "Required for set; max 4000 characters.", maxLength=4000),
                }, ["operation", "scope"]),
            },
            {
                "name": "goal",
                "description": "Read a visible line's goal or set it where authorized.",
                "inputSchema": _schema({
                    "operation": _prop("string", "get or set.", enum=["get", "set"]),
                    "conv_id": _prop("string", "Visible line; defaults to your line."),
                    "goal": _prop("string", "Required for set; max 3000 characters.", maxLength=3000),
                }, ["operation"]),
            },
        ])
    if "write" in actions or "assign" in actions:
        tools.append({
            "name": "post_message",
            "description": "Post to another line; own-line posting is refused to avoid duplicate speech.",
            "inputSchema": _schema({
                "conv_id": _prop("string", "Target line, different from your own."),
                "body": _prop("string", "Message text.", minLength=1),
                "client_key": _prop("string", "Stable retry key, 1 to 64 characters.",
                                     minLength=1, maxLength=64),
            }, ["conv_id", "body", "client_key"]),
        })
    if "write" in actions:
        tools.append({
            "name": "upload_file",
            "description": "Upload one caller-readable local file with bounded streaming.",
            "inputSchema": _schema({
                "conv_id": _prop("string", "Target visible line; defaults to your line."),
                "path": _prop("string", "Readable local file path."),
                "title": _prop("string", "Optional title.", maxLength=200),
                "description": _prop("string", "Optional description.", maxLength=2000),
                "body": _prop("string", "Optional caption.", maxLength=3000),
                "client_key": _prop("string", "Stable retry key, 1 to 64 characters.",
                                     minLength=1, maxLength=64),
            }, ["path", "client_key"]),
        })
    if "write" in actions:
        tools.append(multi_upload_tool())
    if "read" in actions:
        tools.extend([
            {
                "name": "get_media",
                "description": "Download a media variant to a new file with a hard size bound.",
                "inputSchema": _schema({
                    "file_id": _prop("string", "Media id from a Partyline file reference."),
                    "variant": _prop("string", "Media variant.",
                                     enum=["original", "thumb", "slim", "readable"]),
                    "destination": _prop("string", "New local destination path."),
                }, ["file_id", "variant", "destination"]),
            },
        ])
    if ({"read_reports", "report", "notify"} & actions
            and not (state.get("kind") == "machine" and state.get("role") == "lead"
                     and state.get("is_lead") is True)):
        tools.append({
            "name": "reports",
            "description": "Read reports or post a report where authorized.",
            "inputSchema": _schema({
                "operation": _prop("string", "list, get or post.", enum=["list", "get", "post"]),
                "report_id": _prop("integer", "Report id for get.", minimum=1),
                "limit": _prop("integer", "Reports per list page, newest first; default 50.",
                               minimum=1, maximum=200),
                "before_id": _prop("integer", "List reports older than this id.", minimum=1),
                "body": _prop("string", "Report body for post; at most 2000 characters.", maxLength=2000),
                "notify": _prop("boolean", "Wake the parent lead when posting."),
            }, ["operation"]),
        })
    if "write" in actions:
        tools.append({
            "name": "react",
            "description": "Toggle a reaction on a message in your own line; POST adds or removes it.",
            "inputSchema": _schema({
                "message_id": _prop("integer", "Message id."),
                "emoji": _prop("string", "Supported reaction emoji."),
                "remove": _prop("boolean", "Use DELETE to remove; omit or set false to toggle with POST."),
            }, ["message_id", "emoji"]),
        })
    return tools


def _target(client, home_state, conv_id, allowed):
    conv_id = conv_id or client.home
    state = home_state if conv_id == client.home else client.capabilities(conv_id)
    actions = set(state.get("actions", []))
    if not any(action in actions for action in allowed):
        raise ApiError("current attachment is not authorized for that line operation")
    return conv_id, state


def call(client, name: str, args: dict, home_state: dict):
    if name == "whoami":
        return _whoami(client, home_state)
    if name == "guide":
        category, topic = args.get("category"), args.get("topic")
        if topic == "captain" and not category:
            return tools_captain.guide(home_state)
        if not (home_state.get("kind") == "machine"
                and home_state.get("role") == "lead"
                and home_state.get("is_lead") is True):
            return {"title": "Partyline MCP tools",
                    "description": "Available tools and schemas for this attachment's current permissions.",
                    "tools": tool_list(home_state)}
        path = "/api/docs"
        if category:
            path += "/" + quote(category, safe="")
        if topic:
            if not category:
                raise ValueError("category is required when topic is set")
            path += "/" + quote(topic, safe="")
        return client.request("GET", path)
    if name == "read_messages":
        conv, _ = _target(client, home_state, args.get("conv_id"), ("read",))
        limit = max(1, min(int(args.get("limit", 20)), 50))
        if args.get("around_id") is not None:
            query = f"message_id={int(args['around_id'])}&limit={limit}"
            return client.request("GET", f"/api/conversations/{quote(conv, safe='')}/messages/around?{query}")
        query = [f"limit={limit}"]
        for key in ("after_id", "before_id"):
            if args.get(key) is not None:
                query.append(f"{key}={int(args[key])}")
        return client.request("GET", f"/api/conversations/{quote(conv, safe='')}/messages?{'&'.join(query)}")
    if name == "post_message":
        conv = args.get("conv_id", "")
        if not conv or conv == client.home:
            raise ValueError("post_message requires an authorized line other than your own")
        if not args.get("body", "").strip() or not args.get("client_key"):
            raise ValueError("body and a stable client_key are required")
        if len(args["client_key"]) > 64:
            raise ValueError("client_key is capped at 64 characters")
        # Cross-line sibling messages are an explicit route-level exception
        # that the generic capability list cannot express. Refresh target
        # state here, then let the message route make the final decision.
        if conv != client.home:
            client.capabilities(conv)
        return client.request("POST", f"/api/conversations/{quote(conv, safe='')}/messages",
                              {"body": args["body"], "client_key": args["client_key"]})
    if name == "react":
        method = "DELETE" if args.get("remove") else "POST"
        path = f"/api/messages/{int(args['message_id'])}/reactions"
        if method == "DELETE":
            path += "/" + quote(args["emoji"], safe="")
        return client.request(method, path, None if method == "DELETE" else {"emoji": args["emoji"]})
    if name == "get_media":
        return client.download(args["file_id"], args["variant"], args["destination"])
    if name == "upload_files":
        metadata = {key: args.get(key, "") for key in ("title", "description", "body")}
        validate_uploads(args["paths"], client_key=args["client_key"],
                         max_upload=MAX_UPLOAD, **metadata)
        conv, _ = _target(client, home_state, args.get("conv_id"), ("write",))
        if conv == client.home and metadata["body"].strip():
            raise ValueError("an upload caption cannot post free prose on your own line")
        return client.upload_files(conv, args["paths"], client_key=args["client_key"], **metadata)
    if name == "upload_file":
        conv, _ = _target(client, home_state, args.get("conv_id"), ("write",))
        body = args.get("body", "")
        if conv == client.home and body.strip():
            raise ValueError("an upload caption cannot post free prose on your own line")
        return client.upload(conv, args["path"], title=args.get("title", ""),
                             description=args.get("description", ""), body=body,
                             client_key=args["client_key"])
    if name == "notes":
        return _notes(client, home_state, args)
    if name == "goal":
        return _goal(client, home_state, args)
    if name == "reports":
        return _reports(client, home_state, args)
    raise ValueError("unknown MCP tool")


def _whoami(client, state):
    conv = client.home
    detail = client.request("GET", f"/api/conversations/{quote(conv, safe='')}")
    line = detail.get("conversation", {}) if isinstance(detail, dict) else {}
    members = [{key: item.get(key) for key in ("id", "name", "status", "is_lead", "adapter")}
               for item in detail.get("attachments", []) if isinstance(item, dict)]
    children = client.request("GET", f"/api/conversations/{quote(conv, safe='')}/children")
    return {"identity": client.connection["handle"], "attachment_id": client.connection["attachment_id"],
            "line": {"id": conv, "name": line.get("name"), "topic": line.get("topic")},
            "role": state.get("role"), "capabilities": state.get("actions", []),
            "members": members, "parent_id": state.get("parent_id"),
            "children": [{"id": row.get("id"), "name": row.get("name")}
                         for row in children if isinstance(row, dict)]}


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
