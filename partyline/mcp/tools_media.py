"""Media tool schemas and local preflight, separate from core dispatch."""

from pathlib import Path


MODEL_EXTENSIONS = frozenset({".glb", ".gltf"})


def validate_model_path(path: str) -> None:
    if Path(path).suffix.lower() not in MODEL_EXTENSIONS:
        raise ValueError("upload_3d_model requires a .glb or .gltf file")


def model_upload_tool():
    from .tools_core import _prop, _schema

    return {
        "name": "upload_3d_model",
        "description": (
            "Upload one self-contained glTF/GLB 3D model (.gltf or .glb), at most 64 MiB. "
            "It appears as an inline click-to-load 3D card with download; original bytes "
            "are preserved. Extension matching is case-insensitive."
        ),
        "inputSchema": _schema({
            "conv_id": _prop("string", "Target visible line; defaults to your line."),
            "path": _prop("string", "Readable local .glb or .gltf file path."),
            "title": _prop("string", "Optional title.", maxLength=200),
            "client_key": _prop("string", "Stable retry key, 1 to 64 characters.",
                                 minLength=1, maxLength=64),
        }, ["path", "client_key"]),
    }


def multi_upload_tool():
    from .tools_core import _prop, _schema

    return {
        "name": "upload_files",
        "description": (
            "Upload 1 to 6 readable local files in order in ONE chat message, using bounded "
            "streaming (20 MiB each, 60 MiB total). Images (png/jpg/gif/webp, detected by "
            "content, not extension) get thumb/slim/readable/original variants and render "
            "as an inline gallery whose thumbs open a full-size viewer with download. "
            "Self-contained glTF/GLB models appear as inline click-to-load 3D cards. "
            "Other files are generic downloadable attachments; original bytes are "
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
