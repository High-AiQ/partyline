"""Durable digest lines for files posted on a line.

Agents read these as the message body; humans see them stripped in the feed.
The image line is the historical three-tier form. Audio, video, and generic
files carry kind, mime, size, and the original URL. Every image URL is
labelled with the format actually served, so a process knows what it can
decode before it spends a fetch.
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

# Labels for the mimes this server produces; anything else falls back to its
# subtype in upper case, so a label never lies by omission.
_MIME_LABELS = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
    "image/avif": "AVIF",
    "image/heic": "HEIC",
    "image/heif": "HEIF",
    "image/jxl": "JXL",
    "image/bmp": "BMP",
    "image/tiff": "TIFF",
}

# Encodings an agent's tooling reads as-is. An image whose original is
# anything else must carry a readable PNG or be marked as unseen-able.
_DIRECT_FORMATS = frozenset({"PNG", "JPEG", "GIF", "WEBP"})


def _format_label(mime: str | None) -> str:
    if not mime:
        return "unknown"
    return _MIME_LABELS.get(mime) or mime.partition("/")[2].upper() or mime.upper()


def digest_label(ref: FileRef) -> str:
    """Image: title-first. Other kinds: filename, else title/description."""
    if ref.kind == "image":
        # Image lines stay title-first so existing agent readers keep working.
        title = ref.title or ("image" if not ref.description else None)
        return " — ".join(part for part in (title, ref.description) if part)
    title = ref.filename or ref.title or ("file" if not ref.description else None)
    return " — ".join(part for part in (title, ref.description) if part)


def digest_line(ref: FileRef, base: str) -> str:
    """One line per file, listing the URLs a process can fetch, with formats."""
    label = digest_label(ref)
    if ref.kind != "image":
        return (
            f"{_PREFIX.get(ref.kind, '📎')} {label} · {ref.mime} · {formatted_size(ref.bytes)}"
            f" · original: {base}/api/media/{ref.id}/original"
        )
    parts = [f"📷 {label}"]
    if ref.width and ref.height:
        parts.append(f"{ref.width}×{ref.height}")
    if ref.thumb:
        parts.append(f"thumb: {base}/api/media/{ref.id}/thumb ({_format_label(ref.thumb.mime)})")
    if ref.slim:
        parts.append(f"slim: {base}/api/media/{ref.id}/slim ({_format_label(ref.slim.mime)})")
    if ref.readable:
        parts.append(
            f"readable: {base}/api/media/{ref.id}/readable ({_format_label(ref.readable.mime)})"
        )
    parts.append(f"original: {base}/api/media/{ref.id}/original ({_format_label(ref.mime)})")
    if ref.format is not None and ref.format not in _DIRECT_FORMATS and ref.readable is None:
        parts.append("original format not agent-readable")
    return " · ".join(parts)


def digest_body(caption: str, refs: list[FileRef], base: str) -> str:
    lines = [caption.strip()] if caption.strip() else []
    lines.extend(digest_line(ref, base) for ref in refs)
    return "\n".join(lines)
