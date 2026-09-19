"""Byte-signature detection and decoding for uploaded images.

Filenames and declared content types lie; the first bytes of a file do not.
This module names a format from its magic number, decodes what Pillow can,
and calls on ffmpeg for what it cannot — so every limit and derived tier in
``media_images`` can stay a statement about pixels, not containers.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image

# A modest pixel ceiling refuses a decompression bomb before Pillow ever
# allocates the full raster for it.
MAX_PIXELS = 50_000_000

_SIGNATURE_PREFIXES = (
    (b"\x89PNG\r\n\x1a\n", "PNG", "image/png", "png"),
    (b"\xff\xd8\xff", "JPEG", "image/jpeg", "jpg"),
    (b"GIF8", "GIF", "image/gif", "gif"),
    (b"BM", "BMP", "image/bmp", "bmp"),
    (b"II*\x00", "TIFF", "image/tiff", "tif"),
    (b"MM\x00*", "TIFF", "image/tiff", "tif"),
)
_AVIF_BRANDS = frozenset({"avif", "avis", "av01"})
_HEIC_BRANDS = frozenset({"heic", "heix", "hevc", "hevx"})
_HEIF_BRANDS = frozenset({"mif1", "msf1", "mif2", "heim", "heis", "hevm", "hevs"})

# Encodings Pillow usually cannot open without an optional plugin. When the
# magic bytes name one of these and no local decoder exists, the upload is
# kept and marked rather than refused: the file is real, the machine just
# cannot see it yet.
EXTERNAL_FORMATS = frozenset({"AVIF", "HEIC", "HEIF", "JXL"})


class MediaError(Exception):
    """A refusal carrying the HTTP status the caller should see."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _open(data: bytes) -> Image.Image:
    """Decode bytes into a Pillow image. Module-level so tests can fault it."""
    return Image.open(BytesIO(data))


def sniffed_format(data: bytes) -> tuple[str, str, str] | None:
    """Name an image format from its magic bytes: ``(name, mime, extension)``.

    AVIF and friends are identified by their ISOBMFF brand, so an upload no
    local decoder can open is still known, served, and labelled truthfully.
    """
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].decode("ascii", "replace").lower()
        if brand in _AVIF_BRANDS:
            return ("AVIF", "image/avif", "avif")
        if brand in _HEIC_BRANDS:
            return ("HEIC", "image/heic", "heic")
        if brand in _HEIF_BRANDS:
            return ("HEIF", "image/heif", "heif")
    if data.startswith(b"\xff\x0a") or data.startswith(b"\x00\x00\x00\x0cJXL "):
        return ("JXL", "image/jxl", "jxl")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ("WEBP", "image/webp", "webp")
    for prefix, name, mime, ext in _SIGNATURE_PREFIXES:
        if data.startswith(prefix):
            return (name, mime, ext)
    return None


def _ffmpeg_png(data: bytes) -> bytes | None:
    """One PNG frame decoded by ffmpeg, for formats Pillow cannot open.

    ffmpeg is a fallback, not a dependency: absent, failing, or slow, the
    upload falls through to whatever handles a missing decoder. The pixel
    cap is part of the argv, not an afterthought: an adversarial file must
    be refused by the decoder itself, before the raster exists.
    """
    if not shutil.which("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        source, target = Path(tmp) / "upload", Path(tmp) / "readable.png"
        source.write_bytes(data)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-max_pixels", str(MAX_PIXELS), "-i", str(source),
                 "-frames:v", "1", str(target)],
                capture_output=True, timeout=60, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if target.is_file():
            return target.read_bytes()
    return None


def rescued(data: bytes, sniff: tuple[str, str, str] | None) -> Image.Image | None:
    """Decode bytes Pillow refused, via ffmpeg, when the format is known."""
    if sniff is None or sniff[0] not in EXTERNAL_FORMATS:
        return None
    png = _ffmpeg_png(data)
    if png is None:
        return None
    try:
        image = _open(png)
        if image.width * image.height > MAX_PIXELS:
            raise MediaError(413, f"image exceeds {MAX_PIXELS // 1_000_000} megapixels")
        image.load()
    except MediaError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return image
