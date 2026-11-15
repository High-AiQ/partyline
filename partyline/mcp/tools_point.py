"""Point input on a shared window: scroll, drag, type and key, beside screen_window_click.

The order of preference is fixed: screen_elements to read, screen_element_action to act. A point tool is for
what the tree cannot do or an action that failed, and a failure answer already carries the picture (a
`screenshot` with numbered marks and a snapshot id) to point with. Never click with a script.
"""
GUIDE = ("Last resort: read with screen_elements and act with screen_element_action first; use this "
         "only when they cannot do it or an action failed (its answer then carries a `screenshot` with "
         "marks and a snapshot id to use here). Never click or type with page scripts. ")
SAFETY = ("Same rules as screen_window_click: the window must not have moved, resized or closed since the "
          "snapshot, and the point must be in its client area. A Chrome page with a debugging connection "
          "gets the input without the mouse; any other window takes the real mouse and keyboard after "
          "the person agrees on their computer, once per window grant. Never a terminal, password manager "
          "or system dialog. Answers with route (cdp or cursor), settle and what changed; capture=thumb "
          "adds a picture afterwards. landing reports image/screen points, DPI, hit HWND/class, foreground; "
          "unchanged outcomes include a crosshair landing_thumb. ")
WINDOW = {"type": "string",
          "description": "Window grant id or title; includes grants inherited from ancestors."}
CAPTURE = {"type": "string", "enum": ["none", "thumb"],
           "description": "thumb: also return a thumbnail picture taken afterwards."}
SNAPSHOT = {"type": "string", "minLength": 1, "maxLength": 64,
            "description": "The id returned by screen_window_snapshot; the points are its pixels."}


def pixel(description):
    return {"type": "integer", "minimum": 0, "maximum": 100000, "description": description}


def spot(description):
    return {"type": "object", "additionalProperties": False, "required": ["x", "y"],
            "description": description,
            "properties": {"x": pixel("X in the snapshot image."), "y": pixel("Y in the snapshot image.")}}


def steps(description):
    return {"type": "integer", "minimum": -50, "maximum": 50, "description": description}


SCROLL = ("Scroll the wheel at a point of a screen_window_snapshot: dy > 0 scrolls up, dx > 0 right, in "
          "wheel steps. ")
DRAG = ("Press the left button at a point, move through the path and release at another, both points of one "
        "screen_window_snapshot. Plain mouse input: it moves sliders, selections and canvases, but pages "
        "that use HTML5 drag-and-drop may not react. ")
TYPE = ("Type text into the field focused by an earlier screen_window_click in this grant (click it first); "
        "at most 500 characters. Refused when the focused field is a password field or cannot be inspected. ")
KEY = ("Press one key combo such as enter, ctrl+a or shift+tab in the window, after an earlier "
       "screen_window_click in this grant. Lock, log-out and session combos, clipboard combos and alt+f4 are "
       "refused; so are the Windows key and window switchers on the real keyboard. A key that would type "
       "into a password field is refused. ")
TOOLS = {
    "screen_window_scroll": (GUIDE + SCROLL + SAFETY, {
        "window": WINDOW, "snapshot": SNAPSHOT, "x": pixel("X in the snapshot image."),
        "y": pixel("Y in the snapshot image."), "dx": steps("Horizontal wheel steps; positive is right."),
        "dy": steps("Vertical wheel steps; positive is up."), "capture": CAPTURE}, ["snapshot", "x", "y"]),
    "screen_window_drag": (GUIDE + DRAG + SAFETY, {
        "window": WINDOW, "snapshot": SNAPSHOT, "from": spot("Where the button goes down."),
        "to": spot("Where it is released."), "capture": CAPTURE}, ["snapshot", "from", "to"]),
    "screen_window_type": (GUIDE + TYPE + SAFETY, {
        "window": WINDOW, "text": {"type": "string", "minLength": 1, "maxLength": 500,
                                   "description": "Text to type; new lines and tabs are keys."},
        "capture": CAPTURE}, ["text"]),
    "screen_window_key": (GUIDE + KEY + SAFETY, {
        "window": WINDOW, "keys": {"type": "string", "minLength": 1, "maxLength": 64,
                                   "description": "Modifiers (ctrl, alt, shift) plus one key."},
        "capture": CAPTURE}, ["keys"]),
}
NAMES = frozenset(TOOLS)


def tools():
    return [{"name": name, "description": note, "inputSchema": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}
        for name, (note, properties, required) in TOOLS.items()]


def path(name):
    return "/window-" + name.removeprefix("screen_window_")
