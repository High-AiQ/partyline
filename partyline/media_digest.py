"""Durable digest lines for files posted on a line.

Agents read these as the message body; humans see them stripped in the feed.
The image line is the historical three-tier form. Audio, video, and generic
files carry kind, mime, size, and the original URL.
"""

from __future__ import annotations

from .media_contracts import FileKind, FileRef
from .media_files import formatted_size

_PREFIX: dict[FileKind, str] = {
    "image": "📷",
    "audio": "🎵",
    "video": "🎬",
    "file": "📎",
}


def digest_label(ref: FileRef) -> str:
    """Image: title-first. Other kinds: filename, else title/description."""
    if ref.kind == "image":
        # Image lines stay title-first so existing agent readers keep working.
        title = ref.title or ("image" if not ref.description else None)
        return " — ".join(part for part in (title, ref.description) if part)
    title = ref.filename or ref.title or ("file" if not ref.description else None)
    return " — ".join(part for part in (title, ref.description) if part)


def digest_line(ref: FileRef, base: str) -> str:
    """One line per file, listing the URLs a process can fetch."""
    label = digest_label(ref)
    original = f"{base}/api/media/{ref.id}/original"
    if ref.kind == "image":
        return (
            f"📷 {label} · {ref.width}×{ref.height}"
            f" · thumb: {base}/api/media/{ref.id}/thumb"
            f" · slim: {base}/api/media/{ref.id}/slim"
            f" · original: {original}"
        )
    return (
        f"{_PREFIX.get(ref.kind, '📎')} {label} · {ref.mime} · {formatted_size(ref.bytes)}"
        f" · original: {original}"
    )


def digest_body(caption: str, refs: list[FileRef], base: str) -> str:
    lines = [caption.strip()] if caption.strip() else []
    lines.extend(digest_line(ref, base) for ref in refs)
    return "\n".join(lines)
