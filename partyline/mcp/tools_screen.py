"""Screen inspection MCP contract."""


def screen_frame_tool():
    return {
        "name": "screen_frame",
        "description": (
            "Inspect the active screen share; stores line-scoped media without a chat post. "
            "Use get_media to fetch it; mark_pointer labels the reported pointer. Unavailable during "
            "a Show me recording; use the completed walkthrough's image references."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"mark_pointer": {"type": "boolean",
                                           "description": "Overlay the reported pointer."}},
            "required": [],
            "additionalProperties": False,
        },
    }
