"""Multi-file tool schema, kept separate from core operation dispatch."""


def multi_upload_tool():
    from .tools_core import _prop, _schema

    return {
        "name": "upload_files",
        "description": (
            "Upload 1 to 6 readable local files in order in ONE chat message, using bounded "
            "streaming (20 MiB each, 60 MiB total). Images (png/jpg/gif/webp, detected by "
            "content, not extension) get thumb/slim/readable/original variants and render "
            "as an inline gallery whose thumbs open a full-size viewer with download. "
            "Any other file is a generic downloadable attachment; original bytes are "
            "preserved. upload_file remains available for a single file."
        ),
        "inputSchema": _schema({
            "conv_id": _prop("string", "Target visible line; defaults to your line."),
            "paths": _prop("array", "Readable local file paths in display order.",
                           items={"type": "string"}, minItems=1, maxItems=6),
            "title": _prop("string", "Optional title for this message's files.", maxLength=200),
            "description": _prop("string", "Optional description for this message's files.",
                                 maxLength=2000),
            "body": _prop("string", "Optional caption for the single message.", maxLength=3000),
            "client_key": _prop("string", "Stable per-message retry key, 1 to 64 characters.",
                                minLength=1, maxLength=64),
        }, ["paths", "client_key"]),
    }
