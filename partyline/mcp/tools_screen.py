"""Screen inspection MCP contract."""


def screen_frame_tool():
    return {
        "name": "screen_frame",
        "description": (
            "Inspect the active screen share; stores line-scoped media without a chat post. "
            "Use get_media to fetch it; mark_pointer labels the pointer or draws a view-centre "
            "crosshair only when the helper reports captured/hidden. Stationary visible pointers retain "
            "their coordinates and marker. Unavailable during "
            "a Show me recording; use the completed walkthrough's image references."
        ),
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
    "Read the UI Automation tree of a window the person shares (browser pages too, even in the "
    "background). The server keeps the whole window; each answer is at most ~4 KB. No arguments: summary "
    "(counts, outline, pagers and repeated rows with ids). root=<id>: list its children. Find: query "
    "(name), value, control_type; `a|b` either, `=x` or `^x$` exact, `^x`/`x$` ends; `in:` lines name the "
    "ancestors of the lines below. text=true: what a person reads, query greps it. id=<id>: one element in "
    "full. Long answers end with next_offset. Ids stay valid across refresh=true while the element is "
    "unchanged. Act with screen_element_action. Returns elements_unavailable when unavailable.")
ELEMENTS_PROPERTIES = {
    "device": {"type": "string", "description": "Computer name when several are online."},
    "window": {"type": "string", "description": "Window grant id or title when several are shared."},
    "refresh": {"type": "boolean", "description": "Take a new snapshot (after the page changed)."},
    "more": {"type": "boolean", "description": "Continue a capture reported as partial."},
    "root": {"type": "string", "maxLength": 128,
             "description": "Element id: list its children, or limit find/text to its subtree."},
    "depth": {"type": "integer", "minimum": 1, "maximum": 3, "description": "Levels listed under root."},
    "query": {"type": "string", "maxLength": 200,
              "description": "Find by name: substring; a|b, =exact, ^start, end$. With text: grep."},
    "value": {"type": "string", "maxLength": 200, "description": "Find by value (same syntax as query)."},
    "control_type": {"type": "string", "maxLength": 40, "description": "Find: Hyperlink, Button, Edit, ..."},
    "id": {"type": "string", "maxLength": 128, "description": "Read one element whole: full name and value."},
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
