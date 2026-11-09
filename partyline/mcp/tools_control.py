"""Agent control MCP tools: drive the shared screen region after the person's local consent."""

from urllib.parse import quote

from .client import ApiError
from .validation import validate_arguments

FRAME = "integer frame pixel of the latest screen_frame image, (0, 0) at its top left"
NOTE = (" Returns a frame reference after a short settle; fetch its media ID and tier with get_media. "
        "Unchanged frames reuse the last reference. Coordinates use full frame pixels, even for thumbs. "
        "Only inside the shared region, after screen_control_request was granted.")


ELEMENT_ACTION_NOTE = (
    "Use a UIA pattern on any element id from the current screen_elements snapshot (found via find, ls "
    "or text); the element's `actions` list names what it supports. invoke, toggle, set_value(value); "
    "select, add_to_selection, remove_from_selection; expand, collapse; scroll(direction, amount), "
    "set_scroll_percent(horizontal_percent and/or vertical_percent), scroll_into_view; "
    "set_range_value(number, refused outside the element's range); window_close, window_minimize, "
    "window_maximize, window_restore, "
    "window_move(x, y), window_resize(width, height) only on the shared window itself (the first element). "
    "No input is synthesized and the pointer never moves; the app may still bring itself forward and the "
    "result reports foreground_changed / target_came_forward. For dragging use screen_drag.")
ELEMENT_ACTION_PROPERTIES = {
    "window": {"type": "string",
               "description": "Window grant id or title when several windows are shared with you."},
    "element_id": {"type": "string", "minLength": 1, "maxLength": 128},
    "action": {"type": "string", "enum": [
        "invoke", "toggle", "set_value", "select", "add_to_selection", "remove_from_selection", "expand",
        "collapse", "scroll", "set_scroll_percent", "scroll_into_view", "set_range_value", "window_close",
        "window_minimize", "window_maximize", "window_restore", "window_move", "window_resize"]},
    "value": {"type": "string", "maxLength": 500, "description": "Text for set_value."},
    "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "For scroll."},
    "amount": {"type": "string", "enum": ["small", "large"], "description": "For scroll."},
    "horizontal_percent": {"type": "number", "minimum": 0, "maximum": 100,
                           "description": "For set_scroll_percent."},
    "vertical_percent": {"type": "number", "minimum": 0, "maximum": 100,
                         "description": "For set_scroll_percent."},
    "number": {"type": "number", "description": "For set_range_value."},
    "x": {"type": "integer", "minimum": -32768, "maximum": 32767, "description": "Screen X for window_move."},
    "y": {"type": "integer", "minimum": -32768, "maximum": 32767, "description": "Screen Y for window_move."},
    "width": {"type": "integer", "minimum": 1, "maximum": 16384, "description": "For window_resize."},
    "height": {"type": "integer", "minimum": 1, "maximum": 16384, "description": "For window_resize."},
}


def _int(description):
    return {"type": "integer", "description": description}


def _tool(name, description, properties, required):
    if name not in ("screen_control_request", "screen_element_action"):
        properties = {**properties, "frame": {"type": "string", "enum": ["none", "thumb", "full"],
                      "description": "Frame tier: none, thumb (default), or full (original)."}}
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": required,
        "additionalProperties": False}}


def tool_list(state):
    if "write" not in set(state.get("actions", [])):
        return []
    point = {"x": _int("X, " + FRAME + "."), "y": _int("Y, " + FRAME + ".")}
    return [
        _tool("screen_element_action", ELEMENT_ACTION_NOTE, ELEMENT_ACTION_PROPERTIES,
              ["element_id", "action"]),
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
    if name == "screen_element_action":
        return client.request("POST", base + "/element-action", args, timeout=40)
    return client.request("POST", base + "/action", {"kind": name.removeprefix("screen_"), **args})
