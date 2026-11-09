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
    "Read the UI Automation tree of one locally consented Windows window (a browser page too), even in the "
    "background. The person chooses and can revoke the window in the helper tray. The helper captures the "
    "WHOLE window and the server keeps it, so no page is too big; you read it in small pieces "
    "(about 4 KB each) and never get it all at once. Workflow: (1) call with no arguments for a summary: "
    "window title, element count, counts by control type, an outline of the main regions with child "
    "counts and ids. "
    "(2) find: query (case-insensitive substring of name or value; `a|b` means either) and/or control_type "
    "(e.g. Hyperlink) returns only matches, each with its ancestor path (`in: Document > List pager`); "
    "add root=<id> to search inside one element. ls: root=<id> lists its children with their child counts "
    "(depth 1-3). text=true returns the page's visible text in reading order (root=<id> scopes it; query "
    "greps it with `context` lines around each hit). Long answers end with more and next_offset: pass "
    "offset to page. "
    "(3) act: every id is a screen_element_action target (check the [actions] in brackets) until the next "
    "snapshot, so a deep element found by find can be clicked directly. Lines read `id Type \"name\" "
    "=\"value\" [actions] flags`; bounds=true adds screen and frame pixel rectangles. Queries use the stored "
    "snapshot and cost no new read; refresh=true takes a new one after the page changes (ids from the old "
    "snapshot may then be stale). A very large window may report partial: call with more=true to read on. "
    "With several windows, pass window by grant id or title. Returns elements_unavailable when unavailable.")
ELEMENTS_PROPERTIES = {
    "device": {"type": "string", "description": "Computer name when more than one is online."},
    "window": {"type": "string",
               "description": "Window grant id or title; required when several windows are shared with you."},
    "refresh": {"type": "boolean", "description": "Take a new snapshot (invalidates old ids)."},
    "more": {"type": "boolean", "description": "Continue capturing a window reported as partial."},
    "root": {"type": "string", "maxLength": 128,
             "description": "Element id: list its children, or limit find/text to its subtree."},
    "depth": {"type": "integer", "minimum": 1, "maximum": 3, "description": "Levels listed under root (ls)."},
    "query": {"type": "string", "maxLength": 200,
              "description": "Find: case-insensitive name/value substring (a|b = either). With text: grep."},
    "control_type": {"type": "string", "maxLength": 40,
                     "description": "Find: UIA control type such as Hyperlink, Button, Edit, ListItem."},
    "text": {"type": "boolean", "description": "Return visible text instead of elements."},
    "context": {"type": "integer", "minimum": 0, "maximum": 5,
                "description": "Lines of context around each text grep hit (default 1)."},
    "offset": {"type": "integer", "minimum": 0, "description": "Continue a long answer at this offset."},
    "bounds": {"type": "boolean", "description": "Include screen and frame pixel bounds in lines."},
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
