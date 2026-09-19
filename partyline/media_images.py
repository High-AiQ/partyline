"""Decoding, limits, and derived variants for uploaded images.

Nothing here touches the database or the filesystem: an upload is decoded and
either refused with a reason or turned into a value the store can write. That
split is what lets every limit be tested without a server, a temp directory, or
a fixture file. Format detection and external decoding live in
``media_formats``.

Every image gets both derived tiers, unconditionally. The earlier cut skipped
derivation when the original was already small, which meant "the thumbnail" was
sometimes the full original — a 600×600 upload cost a reader the whole file
under a name that promised a cheap one. One shape, always three files, nothing
for a reader to branch on.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .media_formats import (
    EXTERNAL_FORMATS as _EXTERNAL_FORMATS,
    MAX_PIXELS,
    MediaError,
    _open,
    rescued as _rescued,
    sniffed_format,
)

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TITLE = 200
MAX_DESCRIPTION = 2000

# The two derived tiers are jpeg, or png when the source has alpha. They were
# webp — smaller at equal quality — until a local vision model's server (LM
# Studio) refused a webp data URL outright: a process fetched the thumb, as
# the briefing tells it to, and could not show it to its own model. Every
# vision endpoint accepts jpeg and png; the bytes saved were not worth an
# image a model cannot read.
THUMB_MAX_EDGE = 512
SLIM_MAX_EDGE = 1600
DERIVED_QUALITY = 85
THUMB_SUFFIX = "_thumb"
SLIM_SUFFIX = "_slim"

# A fourth tier for encodings an agent cannot decode: the full image
# transcoded to PNG, derived from rather than replacing the original.
READABLE_SUFFIX = "_readable"

FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "GIF": ("image/gif", "gif"),
    "WEBP": ("image/webp", "webp"),
}


@dataclass(frozen=True)
class Derived:
    """One derived variant: the bytes, the size they render at, and its name."""

    data: bytes
    width: int
    height: int
    suffix: str
    mime: str

    @property
    def bytes(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class PreparedImage:
    """A decoded upload and its derivations, held until its row exists.

    ``readable`` is the full-size PNG transcode for encodings agents cannot
    decode; ``None`` when the original bytes already answer every reader.
    """

    data: bytes
    mime: str
    ext: str
    width: int
    height: int
    format: str | None = None
    thumb: Derived | None = None
    slim: Derived | None = None
    readable: Derived | None = None


def _validated_text(value: str | None, limit: int, field: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > limit:
        raise MediaError(400, f"{field} is capped at {limit} characters")
    return text


def validated_metadata(
    title: str | None, description: str | None
) -> tuple[str | None, str | None]:
    """Normalize optional metadata, refusing anything oversized."""
    return (
        _validated_text(title, MAX_TITLE, "title"),
        _validated_text(description, MAX_DESCRIPTION, "description"),
    )


def derived(
    image: Image.Image, max_edge: int | None, suffix: str, *, png: bool = False
) -> Derived:
    """Render one variant at or below ``max_edge``, never enlarging.

    A 400px original yields a 400px thumbnail rather than a blurry 512px one:
    upscaling spends bytes to add nothing a reader can see. ``max_edge`` of
    ``None`` keeps the full size — that is the readable tier, and it is always
    PNG: it exists precisely because some agent cannot decode the source, and
    every vision endpoint reads PNG.
    """
    alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    small = image.convert("RGBA" if alpha else "RGB")
    if max_edge:
        small.thumbnail((max_edge, max_edge))  # Pillow never enlarges here
    buffer = BytesIO()
    if alpha or png:
        small.save(buffer, format="PNG", optimize=True)
        return Derived(buffer.getvalue(), small.width, small.height, suffix + ".png", "image/png")
    small.save(buffer, format="JPEG", quality=DERIVED_QUALITY, optimize=True)
    return Derived(buffer.getvalue(), small.width, small.height, suffix + ".jpg", "image/jpeg")


def _unreadable(data: bytes, sniff: tuple[str, str, str]) -> PreparedImage:
    """Keep an upload no local decoder can open, truthfully marked."""
    name, mime, ext = sniff
    return PreparedImage(data=data, mime=mime, ext=ext, width=0, height=0, format=name)


def _transcoded(
    data: bytes, image: Image.Image, encoding: str | None,
    sniff: tuple[str, str, str] | None,
) -> PreparedImage:
    """Keep the original bytes; derive a full-size PNG every agent can read.

    The stored mime and extension describe what the bytes really are — a
    browser needs that to render the original — while thumb, slim, and
    readable all derive from the transcoded pixels.
    """
    name = encoding or (sniff[0] if sniff else None) or "IMAGE"
    if sniff:
        mime, ext = sniff[1], sniff[2]
    else:
        mime = Image.MIME.get(encoding, "image/" + name.lower())
        ext = next(
            (
                candidate.lstrip(".")
                for candidate, format_name in Image.registered_extensions().items()
                if format_name == encoding
            ),
            "img",
        )
    return PreparedImage(
        data=data, mime=mime, ext=ext, width=image.width, height=image.height,
        format=name,
        thumb=derived(image, THUMB_MAX_EDGE, THUMB_SUFFIX),
        slim=derived(image, SLIM_MAX_EDGE, SLIM_SUFFIX),
        readable=derived(image, None, READABLE_SUFFIX, png=True),
    )


def prepared_image(data: bytes) -> PreparedImage:
    """Decode one upload and derive its tiers, or refuse with a reason.

    Nothing here trusts the client's filename or declared content type: the
    bytes are decoded, and what they decode to is what gets stored. An
    encoding agents cannot read natively keeps its original untouched and
    gains a full-size PNG ``readable`` tier instead.
    """
    if not data:
        raise MediaError(400, "an image upload cannot be empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError(413, f"each image is capped at {MAX_IMAGE_BYTES // (1024 * 1024)}MB")
    sniff = sniffed_format(data)
    try:
        image = _open(data)
        # Read the format off the *opened* image and keep it: rotating below
        # returns a new image whose ``format`` is None, and reading it after
        # that rejects every upload as "unknown". The tests caught exactly
        # that, which is why the order here is load-bearing rather than taste.
        encoding = image.format
        # Animation must be read before the EXIF transpose: it returns a copy
        # of the first frame for animated sources, losing ``is_animated``.
        animated = bool(getattr(image, "is_animated", False))
        if image.width * image.height > MAX_PIXELS:
            raise MediaError(413, f"image exceeds {MAX_PIXELS // 1_000_000} megapixels")
        image.load()
        # A phone photograph is stored in sensor orientation with an EXIF tag
        # saying which way is up. The recorded width and height have to be the
        # ones a viewer will actually see, or a portrait photo is described to
        # every agent on the line as landscape.
        image = ImageOps.exif_transpose(image) or image
    except MediaError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        image = _rescued(data, sniff)
        if image is None:
            if sniff is not None and sniff[0] in _EXTERNAL_FORMATS:
                return _unreadable(data, sniff)
            raise MediaError(400, f"that upload is not a readable image: {exc}") from exc
        encoding = None
    if encoding in FORMATS and not (encoding == "WEBP" and animated):
        mime, ext = FORMATS[encoding]
        return PreparedImage(
            data=data, mime=mime, ext=ext, width=image.width, height=image.height,
            format=encoding,
            thumb=derived(image, THUMB_MAX_EDGE, THUMB_SUFFIX),
            slim=derived(image, SLIM_MAX_EDGE, SLIM_SUFFIX),
        )
    return _transcoded(data, image, encoding, sniff)
