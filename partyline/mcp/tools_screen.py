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


def screen_elements_tool():
    return {"name": "screen_elements", "description": (
        "Read the UI Automation snapshot of one locally consented Windows window, even in the background. "
        "The person chooses and can revoke the window in the helper tray, independent of pixel sharing. "
        "Element IDs are action targets only for the latest snapshot; each element lists its UIA "
        "patterns and the screen_element_action `actions` it supports. "
        "A browser page's Document is read before the toolbars. When truncated is true, the truncation "
        "line says what was left unread (for example page content not reached): retry rather than "
        "assume the page is empty. "
        "Returns elements_unavailable when unavailable."),
        "inputSchema": {"type": "object", "properties": {"device": {"type": "string",
        "description": "Paired computer name when more than one is online."}},
        "required": [], "additionalProperties": False}}
