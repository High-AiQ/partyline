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
    "Read a window shared with this line (Windows UI Automation, not DOM; ~4 KB). No arguments: "
    "summary. find by query/name, value, control_type; root=<id> lists children; text=true reads text; "
    "id=<id> reads one element; inspect=<id> compares live UIA with the stored snapshot and event clock. "
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


def screen_elements_tool():
    return {"name": "screen_elements", "description": ELEMENTS_NOTE,
            "inputSchema": {"type": "object", "properties": ELEMENTS_PROPERTIES, "required": [],
                            "additionalProperties": False}}


def elements_query(args):
    from urllib.parse import quote
    pairs = [f"{key}={quote(str(args[key]), safe='')}" for key in ELEMENTS_PROPERTIES
             if key not in ELEMENTS_FLAGS and args.get(key) not in (None, "")]
    pairs += [f"{key}=true" for key in ELEMENTS_FLAGS if args.get(key)]
    return "?" + "&".join(pairs) if pairs else ""


def call(client, name, args, state, conv):
    from .client import ApiError
    if state.get("dynamic_screen_tools") and not (
            state.get("screen_read") or (name == "screen_elements" and state.get("screen_windows"))):
        raise ApiError("no screen shared with you")
    from urllib.parse import quote
    base = f"/api/conversations/{quote(conv, safe='')}"
    if name == "screen_elements":
        return client.request("POST", base + "/screen-elements" + elements_query(args), timeout=60)
    query = "?mark_pointer=true" if args.get("mark_pointer") else ""
    return client.request("POST", base + "/screen-frame" + query)
