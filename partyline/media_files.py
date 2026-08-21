"""Classification and preparation for arbitrary uploaded files."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import mimetypes
from pathlib import Path
import re

from PIL import Image, UnidentifiedImageError

from .media_contracts import FileKind
from .media_images import Derived, FORMATS, MediaError, prepared_image

MAX_FILES_PER_POST = 6
MAX_FILE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class PreparedFile:
    """Validated bytes and storage metadata for one uploaded file."""

    data: bytes
    kind: FileKind
    filename: str | None
    mime: str
    ext: str
    width: int | None = None
    height: int | None = None
    thumb: Derived | None = None
    slim: Derived | None = None


def sanitized_filename(filename: str | None) -> str | None:
    """Return a display-safe basename, never an uploader-controlled path."""
    if not filename:
        return None
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    basename = "".join(char for char in basename if ord(char) >= 32 and ord(char) != 127)
    if basename in ("", ".", ".."):
        return None
    return basename[:255]


def _declared_mime(content_type: str | None) -> str | None:
    mime = (content_type or "").partition(";")[0].strip().lower()
    if re.fullmatch(r"[^\s/]+/[^\s/]+", mime):
        return mime
    return None


def resolved_mime(filename: str | None, content_type: str | None) -> str:
    """Resolve a MIME type with the sanitised filename taking precedence."""
    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or _declared_mime(content_type) or "application/octet-stream"


def _extension(filename: str | None, mime: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,16}", suffix):
        return suffix[1:]
    guessed = mimetypes.guess_extension(mime) or ".bin"
    return guessed.lstrip(".")


def _looks_like_supported_image(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data)) as image:
            return image.format in FORMATS
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def _non_image(
    data: bytes, filename: str | None, content_type: str | None
) -> PreparedFile:
    mime = resolved_mime(filename, content_type)
    if mime.startswith("audio/"):
        kind: FileKind = "audio"
    elif mime.startswith("video/"):
        kind = "video"
    else:
        kind = "file"
    return PreparedFile(data, kind, filename, mime, _extension(filename, mime))


def prepared_file(
    upload: tuple[bytes, str | None, str | None]
) -> PreparedFile:
    """Classify one upload from its bytes, then prepare it for storage."""
    data, raw_filename, content_type = upload
    if not data:
        raise MediaError(400, "a file upload cannot be empty")
    if len(data) > MAX_FILE_BYTES:
        raise MediaError(413, f"each file is capped at {MAX_FILE_BYTES // (1024 * 1024)}MB")
    filename = sanitized_filename(raw_filename)
    # Above the image cap, identify a supported image without decoding its
    # raster so a real image cannot evade the smaller limit by wearing a
    # non-image filename. Other files remain eligible for the 100 MB limit.
    image_candidate = _looks_like_supported_image(data)
    if image_candidate:
        try:
            image = prepared_image(data)
        except MediaError as exc:
            # A supported header is not enough to make an image: truncated or
            # corrupt bytes fall back to an ordinary file. Safety refusals and
            # the smaller image-size cap are 413s and must remain refusals.
            if exc.status_code != 400:
                raise
        else:
            return PreparedFile(
                image.data,
                "image",
                filename,
                image.mime,
                image.ext,
                image.width,
                image.height,
                image.thumb,
                image.slim,
            )
    return _non_image(data, filename, content_type)


def prepared_files(
    uploads: list[tuple[bytes, str | None, str | None]],
) -> list[PreparedFile]:
    """Prepare a whole post all-or-nothing before any row is written."""
    if not uploads:
        raise MediaError(400, "no file was uploaded")
    if len(uploads) > MAX_FILES_PER_POST:
        raise MediaError(400, f"at most {MAX_FILES_PER_POST} files per post")
    return [prepared_file(upload) for upload in uploads]


def formatted_size(size: int) -> str:
    """Format byte counts compactly for the durable agent digest."""
    value = float(size)
    units = ("B", "KB", "MB", "GB")
    for unit in units:
        if value < 1000 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1000
    raise AssertionError("unreachable")  # pragma: no cover
