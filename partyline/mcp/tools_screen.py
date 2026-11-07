"""Screen inspection MCP contract."""


def screen_frame_tool():
    return {
        "name": "screen_frame",
        "description": (
            "Inspect the active screen share when visual context is needed; stores a media audit item. "
            "Use get_media to fetch it; mark_pointer labels the reported pointer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"mark_pointer": {"type": "boolean",
                                           "description": "Overlay the reported pointer."}},
            "required": [],
            "additionalProperties": False,
        },
    }
