"""Byte-signature detection and decoding for uploaded images.

Filenames and declared content types lie; the first bytes of a file do not.
This module names a format from its magic number, decodes what Pillow can,
and calls on ffmpeg for what it cannot — so every limit and derived tier in
``media_images`` can stay a statement about pixels, not containers.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import logging
import shutil
import subprocess
import tempfile

from PIL import Image

logger = logging.getLogger(__name__)

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

# The codec each external format needs an ffmpeg decoder for. ``ffmpeg
# -decoders`` names every decoder's codec in trailing parentheses, so one
# listing answers capability for every build without probing per file.
_FORMAT_CODECS = {"AVIF": "av1", "HEIC": "hevc", "HEIF": "hevc", "JXL": "jpegxl"}

# ffmpeg rejects an argv it does not understand outright; those markers in
# its stderr mean the build predates an option we pass, not that the file
# is undecodable — worth an error line, never a silent None.
_ARGV_REJECTION = ("unrecognized option", "option not found")

_decoders_listing: str | None = None


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


def reset_decoder_probe() -> None:
    """Forget the cached ffmpeg capability listing (tests re-probe on new PATHs)."""
    global _decoders_listing
    _decoders_listing = None


def ffmpeg_decoders() -> str:
    """The ``ffmpeg -decoders`` listing, probed once; ``''`` when unusable.

    The listing — including an unusable or absent ffmpeg — is cached for the
    process lifetime: installing or upgrading ffmpeg mid-process is seen only
    after a restart.
    """
    global _decoders_listing
    if _decoders_listing is None:
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-decoders"],
                capture_output=True, timeout=60, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            _decoders_listing = ""
        else:
            _decoders_listing = (
                result.stdout.decode("utf-8", "replace") if result.returncode == 0 else ""
            )
    return _decoders_listing


def decodes(format_name: str) -> bool:
    """Whether a local ffmpeg can decode this upload format at all.

    A decoder line names its codec two ways: the leading name column (the
    native ``av1`` and ``hevc`` decoders) or a trailing ``(codec X)`` suffix
    (wrappers like ``libdav1d``). ffmpeg prints that suffix only when the
    name differs from the codec, so a build with only the native decoder
    must be read by name — matching the suffix alone would silently disable
    the rescue path there.
    """
    codec = _FORMAT_CODECS.get(format_name)
    if codec is None:
        return False
    for line in ffmpeg_decoders().splitlines():
        name = line[8:].split(" ", 1)[0] if len(line) > 8 else ""
        if name == codec or line.endswith(f"(codec {codec})"):
            return True
    return False


def _ffmpeg_png(data: bytes, format_name: str) -> bytes | None:
    """One PNG frame decoded by ffmpeg, for formats Pillow cannot open.

    ffmpeg is a fallback, not a dependency: absent or lacking a decoder for
    the format, the upload falls through to whatever handles a missing
    decoder. The pixel cap is part of the argv, not an afterthought: an
    adversarial file must be refused by the decoder itself, before the raster
    exists. A build that rejects the argv outright is a broken rescue path —
    that is logged as an error rather than returned as an anonymous None,
    which once read on CI as "no decoder here" and hid the real cause.
    """
    if not shutil.which("ffmpeg"):
        logger.info("ffmpeg not on PATH; %s upload kept without a readable tier", format_name)
        return None
    if not decodes(format_name):
        logger.info("ffmpeg has no %s decoder; upload kept without a readable tier", format_name)
        return None
    with tempfile.TemporaryDirectory() as tmp:
        source, target = Path(tmp) / "upload", Path(tmp) / "readable.png"
        source.write_bytes(data)
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-max_pixels", str(MAX_PIXELS), "-i", str(source),
                 "-frames:v", "1", str(target)],
                capture_output=True, timeout=60, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.error("ffmpeg %s decode failed: %s", format_name, exc)
            return None
        if target.is_file():
            return target.read_bytes()
        stderr = result.stderr.decode("utf-8", "replace").strip().splitlines()
        reason = stderr[-1] if stderr else f"exit {result.returncode}"
        if any(marker in reason.lower() for marker in _ARGV_REJECTION):
            logger.error(
                "ffmpeg rejected the decode argv for a %s upload (build predates "
                "-max_pixels?): %s", format_name, reason,
            )
        else:
            logger.warning("ffmpeg could not decode the %s upload: %s", format_name, reason)
        return None


def rescued(data: bytes, sniff: tuple[str, str, str] | None) -> Image.Image | None:
    """Decode bytes Pillow refused, via ffmpeg, when the format is known."""
    if sniff is None or sniff[0] not in EXTERNAL_FORMATS:
        return None
    png = _ffmpeg_png(data, sniff[0])
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
