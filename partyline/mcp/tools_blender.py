"""Blender tools: run Python in the person's Blender after their local consent (the local tools relay)."""

from urllib.parse import quote

from .client import ApiError
from .validation import validate_arguments

TOOL = "blender"
NOTE = (" Needs a granted session: call blender_request first and wait for the @mention with the "
        "person's answer. The person can end the session at any time on their computer.")


def _tool(name, description, properties, required):
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}


def tool_list(state):
    if "write" not in set(state.get("actions", [])):
        return []
    return [
        _tool("blender_request",
              "Ask the person on their computer to let you run Python in their Blender (a dialog there; "
              "returns at once, you are @mentioned with the answer). Set checker to also ask permission to "
              "send renders to a hosted checker; on a live session that asks again for only that.", {
                  "checker": {"type": "boolean", "description": "Also ask for render-check permission."},
                  "device": {"type": "string", "maxLength": 120,
                             "description": "Computer name when several are online."}}, []),
        _tool("blender_exec",
              "Run Python in Blender's main thread with bpy available. The namespace persists for the "
              "session. Returns stdout, the last expression's repr, and a structured error with a traceback "
              "when the script raised." + NOTE, {
                  "code": {"type": "string", "minLength": 1, "maxLength": 65536,
                           "description": "Python source; at most 64 KB."},
                  "timeout_s": {"type": "integer", "minimum": 1, "maximum": 120,
                                "description": "Deadline in seconds; default 20."}}, ["code"]),
        _tool("blender_scene_info",
              "Compact JSON about the open scene: objects, types, transforms, camera." + NOTE, {
                  "detail": {"type": "string", "enum": ["summary", "objects", "object"],
                             "description": "summary (default), objects, or one object by name."},
                  "name": {"type": "string", "maxLength": 200,
                           "description": "Object name for detail=object."}}, []),
        _tool("blender_end", "End your Blender session now; the person must approve any later one.", {}, []),
    ]


def call(client, name, args, state):
    available = {tool["name"]: tool for tool in tool_list(state)}
    if name not in available:
        raise ApiError("local tools need write access to your line")
    validate_arguments(available[name]["inputSchema"], args)
    base = f"/api/conversations/{quote(client.home, safe='')}/local-tools"
    if name == "blender_request":
        return client.request("POST", base + "/request", {"tool": TOOL, **args})
    if name == "blender_end":
        return client.request("POST", base + "/end")
    timeout = args.get("timeout_s", 20)
    if name == "blender_exec":
        body = {"op": "exec", "args": {"code": args["code"]}, "timeout_s": timeout}
    else:
        body = {"op": "scene_info", "args": {k: v for k, v in args.items() if k in ("detail", "name")}}
    return client.request("POST", base + "/call", body, timeout=timeout + 15)
