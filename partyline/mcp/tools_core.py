"""Core, named MCP operations backed by fixed Partyline API routes."""
from urllib.parse import quote
from ..upload_scope import UPLOAD_ONLY_CAPTION_REFUSAL
from .client import ApiError, MAX_UPLOAD, MAX_MODEL_UPLOAD
from .pages import message_page
from .uploads import validate_uploads
from .tools_media import GET_MEDIA_DESCRIPTION, model_upload_tool, multi_upload_tool, validate_model_path
from .tools_screen import screen_elements_tool, screen_frame_tool
from . import tools_captain, tools_worker, tools_screen
from .core_ops import _goal, _notes, _reports, _target, _whoami
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
            "description": "Show identity, role, line members, live child lines and a count of retired ones.",
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
    screen_read = (not state.get("dynamic_screen_tools") or state.get("screen_read"))
    screen_elements = (not state.get("dynamic_screen_tools") or state.get("screen_read")
                       or state.get("screen_windows"))
    if "read" in actions:
        tools.extend([
            *([screen_frame_tool()] if screen_read else []),
            *([screen_elements_tool()] if screen_elements else []),
            {
                "name": "read_messages",
                "description": ("Read a bounded page, optionally around a message id. A page too large "
                                "for one reply keeps whole messages; `resume` says where to continue."),
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
            "description": ("Upload one caller-readable local file with bounded streaming. "
                            "Self-contained .glb/.gltf files appear as click-to-load 3D cards."),
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
        tools.extend([model_upload_tool(), multi_upload_tool()])
    if "read" in actions:
        tools.extend([
            {
                "name": "get_media",
                "description": GET_MEDIA_DESCRIPTION,
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

def call(client, name: str, args: dict, home_state: dict):
    if name == "whoami":
        return _whoami(client, home_state)
    if name == "guide":
        category, topic = args.get("category"), args.get("topic")
        from . import catalog
        if topic and not category:
            if topic == "captain":
                return tools_captain.guide(home_state)
            if topic == "worker":
                return tools_worker.guide(home_state)
            entry = catalog.guide_entry(home_state, topic)
            if entry is not None:
                return entry
        if not (category or topic) and not tools_captain.is_lead(home_state):
            return catalog.guide_index(home_state)
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
        around = args.get("around_id")
        query = [f"limit={limit}"] if around is None else [f"message_id={int(around)}", f"limit={limit}"]
        for key in ("after_id", "before_id") if around is None else ():
            if args.get(key) is not None:
                query.append(f"{key}={int(args[key])}")
        path = f"/api/conversations/{quote(conv, safe='')}/messages{'' if around is None else '/around'}"
        return message_page(client.request("GET", f"{path}?{'&'.join(query)}"),
                            around is None and args.get("after_id") is not None, around)
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
    if name in ("screen_elements", "screen_frame"):
        conv, _ = _target(client, home_state, None, ("read",))
        return tools_screen.call(client, name, args, home_state, conv)
    if name == "upload_files":
        metadata = {key: args.get(key, "") for key in ("title", "description", "body")}
        validate_uploads(args["paths"], client_key=args["client_key"],
                         max_upload=MAX_UPLOAD, **metadata)
        conv, target = _target(client, home_state, args.get("conv_id"), ("upload", "write"))
        if metadata["body"].strip() and "write" not in target.get("actions", []):
            raise ApiError(UPLOAD_ONLY_CAPTION_REFUSAL)
        if conv == client.home and metadata["body"].strip():
            raise ValueError("an upload caption cannot post free prose on your own line: "
                             "your terminal reply is the chat message; omit body or pass "
                             "another conv_id")
        return client.upload_files(conv, args["paths"], client_key=args["client_key"], **metadata)
    if name == "upload_3d_model":
        validate_model_path(args["path"])
        conv, _ = _target(client, home_state, args.get("conv_id"), ("upload", "write"))
        return client.upload(conv, args["path"], title=args.get("title", ""),
                             client_key=args["client_key"], max_upload=MAX_MODEL_UPLOAD)
    if name == "upload_file":
        conv, target = _target(client, home_state, args.get("conv_id"), ("upload", "write"))
        body = args.get("body", "")
        if body.strip() and "write" not in target.get("actions", []):
            raise ApiError(UPLOAD_ONLY_CAPTION_REFUSAL)
        if conv == client.home and body.strip():
            raise ValueError("an upload caption cannot post free prose on your own line: "
                             "your terminal reply is the chat message; omit body or pass "
                             "another conv_id")
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
