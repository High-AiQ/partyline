"""Agent control MCP tools: drive the shared screen region after the person's local consent."""

from urllib.parse import quote

from .client import ApiError
from .validation import validate_arguments

FRAME = "integer frame pixel of the latest screen_frame image, (0, 0) at its top left"
NOTE = (" Returns a fresh frame reference after a short settle; fetch it with get_media. "
        "Only inside the shared region, after screen_control_request was granted.")


def _int(description):
    return {"type": "integer", "description": description}


def _tool(name, description, properties, required):
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": required,
        "additionalProperties": False}}


def tool_list(state):
    if "write" not in set(state.get("actions", [])):
        return []
    point = {"x": _int("X, " + FRAME + "."), "y": _int("Y, " + FRAME + ".")}
    return [
        _tool("screen_control_request",
              "Ask the person sharing their screen to let you drive its mouse and keyboard. "
              "Returns at once; you are @mentioned when they answer on their computer.", {}, []),
        _tool("screen_click", "Click at a point in the shared region." + NOTE, {
            **point,
            "button": {"type": "string", "enum": ["left", "right", "middle"],
                       "description": "Mouse button; default left."},
            "double": {"type": "boolean", "description": "Double-click; default false."},
        }, ["x", "y"]),
        _tool("screen_move", "Move the pointer to a point in the shared region." + NOTE, point, ["x", "y"]),
        _tool("screen_drag", "Press the left button at (x1, y1), drag to (x2, y2) and release." + NOTE, {
            "x1": _int("Start X, " + FRAME + "."), "y1": _int("Start Y."),
            "x2": _int("End X."), "y2": _int("End Y."),
        }, ["x1", "y1", "x2", "y2"]),
        _tool("screen_scroll", "Scroll at a point: dy > 0 scrolls up, dx > 0 right, in wheel steps." + NOTE, {
            **point,
            "dx": {"type": "integer", "minimum": -50, "maximum": 50, "description": "Horizontal steps."},
            "dy": {"type": "integer", "minimum": -50, "maximum": 50, "description": "Vertical steps."},
        }, ["x", "y"]),
        _tool("screen_type", "Type text into the focused window (click it first)." + NOTE, {
            "text": {"type": "string", "minLength": 1, "maxLength": 500,
                     "description": "Text to type; at most 500 characters per call."},
        }, ["text"]),
        _tool("screen_key", "Press a key combo such as ctrl+s, enter or alt+tab (click a window first). "
              "Lock, log-out and session combos are blocked." + NOTE, {
                  "keys": {"type": "string", "minLength": 1, "maxLength": 64,
                           "description": "Modifiers (ctrl, alt, shift, meta/cmd/win) plus one key."},
              }, ["keys"]),
    ]


def call(client, name, args, state):
    available = {tool["name"]: tool for tool in tool_list(state)}
    if name not in available:
        raise ApiError("screen control needs write access to your line")
    validate_arguments(available[name]["inputSchema"], args)
    base = f"/api/conversations/{quote(client.home, safe='')}/screen-control"
    if name == "screen_control_request":
        return client.request("POST", base + "/request")
    return client.request("POST", base + "/action", {"kind": name.removeprefix("screen_"), **args})
