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
        _tool("blender_render",
              "Render the open scene and store the image as line media: returns a file reference (like "
              "screen_frame; fetch the pixels with get_media) plus the settings actually used. Sizes and "
              "samples are clamped and every clamp is listed in `adjusted`. Workbench is fast; eevee needs "
              "the person's GPU. A render cannot be interrupted once it is running: a cancel or deadline is "
              "honoured when it finishes and the image is then discarded." + NOTE, {
                  "camera": {"type": "string", "maxLength": 200,
                             "description": "Camera object name; default the scene's active camera."},
                  "width": {"type": "integer", "minimum": 1, "maximum": 100000,
                            "description": "Pixels, clamped to 16..2048; default the scene's size."},
                  "height": {"type": "integer", "minimum": 1, "maximum": 100000,
                             "description": "Pixels, clamped to 16..2048; default the scene's size."},
                  "engine": {"type": "string", "enum": ["workbench", "eevee"],
                             "description": "workbench (default) or eevee."},
                  "samples": {"type": "integer", "minimum": 1, "maximum": 100000,
                              "description": "EEVEE samples, clamped to 1..64; ignored by workbench."},
                  "frame": {"type": "integer", "minimum": -1000000, "maximum": 1000000,
                            "description": "Frame to render, clamped to the scene's range; default current."},
                  "timeout_s": {"type": "integer", "minimum": 1, "maximum": 120,
                                "description": "Deadline in seconds; default 60."}}, []),
        _tool("blender_screenshot",
              "Capture the 3D viewport the person is looking at, off screen, as line media (fetch it with "
              "get_media). Only Blender's viewport; for the whole window use screen_frame." + NOTE, {
                  "max_size": {"type": "integer", "minimum": 1, "maximum": 100000,
                               "description": "Long edge, clamped to 64..1600; default 1024."}}, []),
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
    timeout = args.get("timeout_s", 60 if name == "blender_render" else 20)
    if name == "blender_exec":
        body = {"op": "exec", "args": {"code": args["code"]}, "timeout_s": timeout}
    elif name in ("blender_render", "blender_screenshot"):
        body = {"op": name.removeprefix("blender_"), "timeout_s": timeout,
                "args": {k: v for k, v in args.items() if k != "timeout_s"}}
    else:
        body = {"op": "scene_info", "args": {k: v for k, v in args.items() if k in ("detail", "name")}}
    return client.request("POST", base + "/call", body, timeout=timeout + 15)
