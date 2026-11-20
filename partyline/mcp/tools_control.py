"""Agent control MCP tools: drive the shared screen region after the person's local consent."""

from urllib.parse import quote

from .client import ApiError
from .tools_point import NAMES as POINT_NAMES, path as point_path, tools as point_tools
from .validation import validate_arguments

FRAME = "integer frame pixel of the latest screen_frame image, (0, 0) at its top left"
NOTE = (" Returns a frame reference after a short settle; fetch its media ID and tier with get_media. "
        "Unchanged frames reuse the last reference. Coordinates use full frame pixels, even for thumbs. "
        "Only inside the shared region, after screen_control_request was granted.")


ELEMENT_ACTION_NOTE = (
    "Act on screen_elements IDs or latest screen_window_look mark=n; never reuse marks; never script clicks. "
    "CDP/UIA; other invoke/click marks use guarded points (landed_in). "
    "set_values fills 1–8 fields; then.root reads controls once; stops on error, never retries. "
    "set_files: 1–10 media IDs/paths, 200 MiB. select takes value; "
    "set_value edits; press: enter/tab/escape; force overrides disabled. then reads changes; "
    "then.snapshot adds a picture. Failures carry screenshot marks for screen_window_click. "
    'reload/dialog use element_id="page". dialog requires accept; '
    'beforeunload accept=true leaves and discards unsaved changes. '
    'UIA window_* targets the window; drag: screen_drag.')
ELEMENT_ACTION_TIMEOUT = 125  # a 20s capture, a 35s exchange, the action, then a 20s failure picture
WINDOW_CLICK_TIMEOUT = 150  # helper 70s, requested after/crosshair/failure pictures 20s each, plus margin
ELEMENT_ACTION_THEN_TIMEOUT = 160  # also allow a post-action capture and event barrier
ELEMENT_ACTION_PROPERTIES = {
    "window": {"type": "string",
               "description": "Window grant id or title; includes grants inherited from ancestors."},
    "force": {"type": "boolean", "description": "Try a reported-disabled control the person confirms works."},
    "mark": {"type": "integer", "minimum": 1, "description": "Latest look box; alternative to element_id."},
    "element_id": {"type": "string", "minLength": 1, "maxLength": 128},
    "action": {"type": "string", "enum": [
        "click", "invoke", "toggle", "set_value", "set_values", "set_files", "press", "select",
        "add_to_selection", "remove_from_selection", "expand", "collapse", "scroll", "set_scroll_percent",
        "scroll_into_view", "set_range_value", "window_close",
        "window_minimize", "window_maximize", "window_restore", "window_move", "window_resize",
        "reload", "dialog"]},
    "files": {"type": "array", "minItems": 1, "maxItems": 10,
              "items": {"type": "string", "minLength": 1, "maxLength": 128},
              "description": "For set_files: readable Partyline media IDs."},
    "paths": {"type": "array", "minItems": 1, "maxItems": 10,
              "items": {"type": "string", "minLength": 1, "maxLength": 32767},
              "description": "For set_files: absolute file paths on the paired computer."},
    "value": {"type": "string", "maxLength": 500,
              "description": "Text for set_value; option name for ComboBox select."},
    "assignments": {
        "type": "array", "minItems": 1, "maxItems": 8,
        "description": "For set_values: ordered independent fields, attempted once until one fails.",
        "items": {
            "type": "object", "additionalProperties": False,
            "required": ["element_id", "value"], "properties": {
                "element_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "value": {"type": "string", "maxLength": 500},
                "action": {"type": "string", "enum": ["set_value", "select"],
                           "description": "Defaults to set_value."}}}},
    "accept": {"type": "boolean", "description": "Required for dialog; explicit accept or dismiss."},
    "prompt_text": {"type": "string", "maxLength": 500, "description": "Optional dialog prompt text."},
    "key": {"type": "string", "enum": ["enter", "tab", "escape"], "description": "For press; no modifiers."},
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
    "then": {"type": "object", "additionalProperties": False, "description": "Snapshot and read afterwards.",
             "properties": {
                 "query": {"type": "string", "maxLength": 200}, "value": {"type": "string", "maxLength": 200},
                 "control_type": {"type": "string", "maxLength": 40},
                 "root": {"type": "string", "maxLength": 128}, "id": {"type": "string", "maxLength": 128},
                 "text": {"type": "boolean"}, "context": {"type": "integer", "minimum": 0, "maximum": 5},
                 "depth": {"type": "integer", "minimum": 1, "maximum": 3},
                 "snapshot": {"type": "boolean", "description": (
                     "Only a thumb picture of the window afterwards, no tree read.")}}},
}


WINDOW_CLICK_NOTE = (
    "Last resort: click a point you see in a screen_window_snapshot of a shared window, only when "
    "screen_elements and screen_element_action cannot do it (a canvas, an odd widget, a control the tree "
    "misses) or an action failed (its answer then carries a `screenshot` with marks and a snapshot id to "
    "use here). Never click with page scripts. Take screen_window_snapshot first (marks=true numbers the "
    "elements and adds a coordinate grid) and pass its id; x and y are that image's pixels, (0, 0) at its "
    "top left. Refused "
    "when the window moved, resized, closed or was re-granted since the snapshot, or when the point is "
    "outside the window's client area. A Chrome page with a debugging connection is clicked without the "
    "mouse; any other window moves the real cursor after the person agrees on their computer, once per "
    "window grant. Never a terminal, password manager or system dialog. Answers with route (cdp or "
    "cursor), settle, and landing evidence (image/screen point, DPI, hit HWND/class, foreground). "
    "Read each point’s landed_in verdict: granted_page, granted_window or other_window (warning). "
    "After a click, read changes before deciding it failed. Changes contain actionable element IDs. "
    "Settling waits on events within the action deadline; still changing is explicit. Unchanged or "
    "still-changing outcomes include one crosshair landing_thumb; capture=thumb adds a picture afterwards.")
WINDOW_CLICK_PROPERTIES = {
    "window": ELEMENT_ACTION_PROPERTIES["window"],
    "snapshot": {"type": "string", "minLength": 1, "maxLength": 64,
                 "description": "The id returned by screen_window_snapshot; the click uses its pixels."},
    "x": {"type": "integer", "minimum": 0, "maximum": 100000, "description": "X in the snapshot image."},
    "y": {"type": "integer", "minimum": 0, "maximum": 100000, "description": "Y in the snapshot image."},
    "button": {"type": "string", "enum": ["left", "right"], "description": "Mouse button; default left."},
    "clicks": {"type": "integer", "enum": [1, 2], "description": "1, or 2 for a double-click."},
    "capture": {"type": "string", "enum": ["none", "thumb"],
                "description": "thumb: also return a thumbnail picture taken after the click."},
}
NO_FRAME = ("screen_control_request", "screen_element_action", "screen_eval", "screen_window_click",
            *sorted(POINT_NAMES))


def _int(description):
    return {"type": "integer", "description": description}


def _tool(name, description, properties, required):
    if name not in NO_FRAME:
        properties = {**properties, "frame": {"type": "string", "enum": ["none", "thumb", "full"],
                      "description": "Frame tier: none, thumb (default), or full (original)."}}
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": required,
        "additionalProperties": False}}


def tool_list(state):
    if state.get("dynamic_screen_tools"):
        if not state.get("screen_read") and not state.get("screen_windows"):
            return []
        allowed = set()
        if state.get("screen_windows"):
            allowed.update({"screen_element_action", "screen_eval", "screen_window_click", *POINT_NAMES})
        if state.get("screen_control"):
            allowed.update({"screen_click", "screen_move", "screen_drag", "screen_scroll",
                            "screen_type", "screen_key"})
        elif state.get("screen_read"):
            allowed.add("screen_control_request")
        actions_enabled = True
    else:
        if "write" not in set(state.get("actions", [])):
            return []
        allowed = None
        actions_enabled = True
    if not actions_enabled:
        return []
    point = {"x": _int("X, " + FRAME + "."), "y": _int("Y, " + FRAME + ".")}
    tools = [
        _tool("screen_eval", "Read page state or navigate with location.assign in the active tab of a shared "
              "Chrome window; bounded JSON. Never click or change the page with JavaScript. Interact with "
              "screen_element_action, which sends trusted input. "
              "Requires an approved Chrome debugging connection. Calls are audited by input length.",
              {"expression": {"type": "string", "minLength": 1, "maxLength": 16000},
               "window": ELEMENT_ACTION_PROPERTIES["window"]}, ["expression"]),
        _tool("screen_element_action", ELEMENT_ACTION_NOTE, ELEMENT_ACTION_PROPERTIES,
              ["action"]),
        _tool("screen_window_click", WINDOW_CLICK_NOTE, WINDOW_CLICK_PROPERTIES, ["snapshot", "x", "y"]),
        *point_tools(),
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
    return [tool for tool in tools if allowed is None or tool["name"] in allowed]


def call(client, name, args, state):
    available = {tool["name"]: tool for tool in tool_list(state)}
    if name not in available:
        if name.startswith("screen_") and state.get("dynamic_screen_tools"):
            raise ApiError("no screen shared with you")
        raise ApiError("screen control needs write access to your line")
    validate_arguments(available[name]["inputSchema"], args)
    base = f"/api/conversations/{quote(client.home, safe='')}/screen-control"
    if name == "screen_eval":
        return client.request("POST", base.removesuffix("/screen-control") + "/screen-eval", args, timeout=60)
    if name == "screen_window_click":
        return client.request("POST", base + "/window-click", args, timeout=WINDOW_CLICK_TIMEOUT)
    if name in POINT_NAMES:
        return client.request("POST", base + point_path(name), args, timeout=WINDOW_CLICK_TIMEOUT)
    if name == "screen_control_request":
        return client.request("POST", base + "/request")
    if name == "screen_element_action":
        wait = (700 if args.get("action") in ("set_files", "set_values") else
                ELEMENT_ACTION_THEN_TIMEOUT if args.get("then") is not None else ELEMENT_ACTION_TIMEOUT)
        return client.request("POST", base + "/element-action", args, timeout=wait)
    return client.request("POST", base + "/action", {"kind": name.removeprefix("screen_"), **args})
