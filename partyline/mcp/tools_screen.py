"""Screen inspection MCP contract."""


def screen_frame_tool():
    return {
        "name": "screen_frame",
        "description": "Capture the shared screen; use get_media to fetch the image.",
        "inputSchema": {
            "type": "object",
            "properties": {"mark_pointer": {"type": "boolean",
                                           "description": ("Overlay the pointer, or a centre crosshair for a "
                                                           "helper-reported hidden/captured cursor. "
                                                           "Stationary pointers keep their position.")}},
            "required": [],
            "additionalProperties": False,
        },
    }


ELEMENTS_NOTE = (
    "Read a shared/inherited window (CDP for Chrome pages, UIA otherwise; ~4 KB; source in header). "
    "No arguments: "
    "summary. find by query/name, value, control_type; root=<id> lists children; text=true reads text; "
    "id=<id> reads one element; inspect=<id> compares live UIA with the stored snapshot and event clock. "
    "Crashed/detached Chrome pages read UIA browser controls with page_state and a reload hint. "
    "Use screen_element_action on ids. Cache reuse requires a live event-counter barrier on new "
    "helpers; old helpers expire after 3 seconds. Answers include snapshot_age_seconds and "
    "change_event_since_snapshot. Refresh with refresh=true; unchanged ids survive. more=true continues."
)
ELEMENTS_PROPERTIES = {
    "device": {"type": "string", "description": "Computer name when several are online."},
    "window": {"type": "string", "description": "Window grant id or title when several are shared."},
    "refresh": {"type": "boolean",
                "description": "Take a fresh snapshot now; unchanged ids stay stable."},
    "more": {"type": "boolean", "description": "Continue a capture reported as partial."},
    "root": {"type": "string", "maxLength": 128,
             "description": "Element id: list its children, or limit find/text to its subtree."},
    "depth": {"type": "integer", "minimum": 1, "maximum": 3, "description": "Levels listed under root."},
    "query": {"type": "string", "maxLength": 200,
              "description": "Find by name: substring; a|b, =exact, ^start, end$. With text: grep."},
    "value": {"type": "string", "maxLength": 200, "description": "Find by value (same syntax as query)."},
    "control_type": {"type": "string", "maxLength": 40, "description": "Find: Hyperlink, Button, Edit, ..."},
    "id": {"type": "string", "maxLength": 128, "description": "Read one element whole: full name and value."},
    "inspect": {"type": "string", "maxLength": 128,
                "description": "Probe live state, ancestors and provider against the stored element."},
    "text": {"type": "boolean", "description": "Return the text a person reads instead of elements."},
    "changes": {"type": "boolean", "description": "List what the last refresh added (offset pages it)."},
    "context": {"type": "integer", "minimum": 0, "maximum": 5, "description": "Lines around each text hit."},
    "offset": {"type": "integer", "minimum": 0, "description": "Continue a long answer here."},
    "bounds": {"type": "boolean", "description": "Add screen and frame pixel rectangles."},
}
ELEMENTS_FLAGS = ("refresh", "more", "text", "bounds")
WINDOW_TOOLS = ("screen_elements", "screen_window_snapshot")  # what a window grant alone allows


def screen_windows_tool():
    return {"name": "screen_windows", "description": "List safe windows on the paired person's computer.",
            "inputSchema": {"type": "object", "properties": {}, "required": [],
                            "additionalProperties": False}}


def screen_attach_window_tool():
    return {"name": "screen_attach_window", "description": (
        "Attach one listed window to this line under the person's standing permission. Give a reason."),
        "inputSchema": {"type": "object", "properties": {
            "window": {"type": "string", "minLength": 1, "maxLength": 2048,
                       "description": "hwnd/id returned by screen_windows."},
            "reason": {"type": "string", "minLength": 1, "maxLength": 500},
        }, "required": ["window", "reason"], "additionalProperties": False}}


def screen_elements_tool():
    return {"name": "screen_elements", "description": ELEMENTS_NOTE,
            "inputSchema": {"type": "object", "properties": ELEMENTS_PROPERTIES, "required": [],
                            "additionalProperties": False}}


WINDOW_SNAPSHOT_NOTE = (
    "One screenshot of a window a person shared with this line, only that window. Not the default: "
    "read screen_elements first, and its deltas after each screen_element_action. Use this when layout or "
    "visuals matter, or when elements do not explain what is on screen. Returns variants full, slim and "
    "thumb (url, size, image tokens); slim is the usual choice; get_media fetches one. Protected content "
    "shows black; the person sees each capture. The answer's snapshot id and pixels are what "
    "screen_window_click takes, for a point elements cannot reach. Crashed Chrome includes source: uia, "
    "page_state and a reload hint."
)
WINDOW_SNAPSHOT_PROPERTIES = {
    **{key: ELEMENTS_PROPERTIES[key] for key in ("device", "window")},
    "marks": {"type": "boolean", "description": (
        "Overlay a light coordinate grid and numbered boxes for the elements of the latest "
        "screen_elements read, listed as {n, id, name, box}. Use with screen_window_click.")}}


def screen_window_snapshot_tool():
    return {"name": "screen_window_snapshot", "description": WINDOW_SNAPSHOT_NOTE,
            "inputSchema": {"type": "object", "properties": WINDOW_SNAPSHOT_PROPERTIES, "required": [],
                            "additionalProperties": False}}


def elements_query(args):
    from urllib.parse import quote
    pairs = [f"{key}={quote(str(args[key]), safe='')}" for key in ELEMENTS_PROPERTIES
             if key not in ELEMENTS_FLAGS and args.get(key) not in (None, "")]
    pairs += [f"{key}=true" for key in ELEMENTS_FLAGS if args.get(key)]
    return "?" + "&".join(pairs) if pairs else ""


def call(client, name, args, state, conv):
    from .client import ApiError
    if name in ("screen_windows", "screen_attach_window") and not state.get("window_access"):
        raise ApiError("no paired computer with window access on is connected for this line")
    standing_tool = name in ("screen_windows", "screen_attach_window") and state.get("window_access")
    if state.get("dynamic_screen_tools") and not (
            state.get("screen_read") or standing_tool
            or (name in WINDOW_TOOLS and state.get("screen_windows"))):
        raise ApiError("no screen shared with you")
    from urllib.parse import quote
    base = f"/api/conversations/{quote(conv, safe='')}"
    if name == "screen_windows":
        return client.request("POST", base + "/screen-windows", {}, timeout=60)
    if name == "screen_attach_window":
        return client.request("POST", base + "/screen-attach-window", args, timeout=60)
    if name == "screen_elements":
        return client.request("POST", base + "/screen-elements" + elements_query(args), timeout=60)
    if name == "screen_window_snapshot":
        pairs = [f"{key}={quote(str(args[key]), safe='')}" for key in ("device", "window") if args.get(key)]
        pairs += ["marks=true"] if args.get("marks") else []
        query = "?" + "&".join(pairs) if pairs else ""
        return client.request("POST", base + "/screen-window-snapshot" + query, timeout=60)
    query = "?mark_pointer=true" if args.get("mark_pointer") else ""
    return client.request("POST", base + "/screen-frame" + query)
