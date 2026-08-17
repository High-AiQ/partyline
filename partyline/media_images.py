"""Decoding, limits, and derived variants for uploaded images.

Nothing here touches the database or the filesystem: an upload is decoded and
either refused with a reason or turned into a value the store can write. That
split is what lets every limit be tested without a server, a temp directory, or
a fixture file.

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

MAX_IMAGES_PER_POST = 6
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# A modest pixel ceiling refuses a decompression bomb before Pillow ever
# allocates the full raster for it.
MAX_PIXELS = 50_000_000
MAX_TITLE = 200
MAX_DESCRIPTION = 2000

# The two derived tiers, both webp: one codec family for everything derived,
# ~25-35% smaller than jpeg at the same perceptual quality, and alpha survives
# — a transparent PNG would need a matte colour invented for it under jpeg.
THUMB_MAX_EDGE = 512
SLIM_MAX_EDGE = 1600
DERIVED_QUALITY = 80
DERIVED_MIME = "image/webp"
THUMB_SUFFIX = "_thumb.webp"
SLIM_SUFFIX = "_slim.webp"

FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "GIF": ("image/gif", "gif"),
    "WEBP": ("image/webp", "webp"),
}


class MediaError(Exception):
    """A refusal carrying the HTTP status the caller should see."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Derived:
    """One derived variant: the bytes, the size they render at, and its name."""

    data: bytes
    width: int
    height: int
    suffix: str

    @property
    def bytes(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class PreparedImage:
    """A decoded upload and both derivations, held until its row exists."""

    data: bytes
    mime: str
    ext: str
    width: int
    height: int
    thumb: Derived
    slim: Derived


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


def derived(image: Image.Image, max_edge: int, suffix: str) -> Derived:
    """Render one variant at or below ``max_edge``, never enlarging.

    A 400px original yields a 400px thumbnail rather than a blurry 512px one:
    upscaling spends bytes to add nothing a reader can see.
    """
    mode = "RGBA" if image.mode in ("RGBA", "LA", "PA", "P") else "RGB"
    small = image.convert(mode)
    small.thumbnail((max_edge, max_edge))  # Pillow never enlarges here
    buffer = BytesIO()
    small.save(buffer, format="WEBP", quality=DERIVED_QUALITY, method=4)
    return Derived(buffer.getvalue(), small.width, small.height, suffix)


def prepared_image(data: bytes) -> PreparedImage:
    """Decode one upload and derive both tiers, or refuse with a reason.

    Nothing here trusts the client's filename or declared content type: the
    bytes are decoded, and what Pillow says they are is what they are.
    """
    if not data:
        raise MediaError(400, "an image upload cannot be empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError(413, f"each image is capped at {MAX_IMAGE_BYTES // (1024 * 1024)}MB")
    try:
        image = Image.open(BytesIO(data))
        # Read the format off the *opened* image and keep it: rotating below
        # returns a new image whose ``format`` is None, and reading it after
        # that rejects every upload as "unknown". The tests caught exactly
        # that, which is why the order here is load-bearing rather than taste.
        encoding = image.format
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
        raise MediaError(400, f"that upload is not a readable image: {exc}") from exc
    if encoding not in FORMATS:
        raise MediaError(400, f"unsupported image format: {encoding or 'unknown'}")
    mime, ext = FORMATS[encoding]
    return PreparedImage(
        data=data,
        mime=mime,
        ext=ext,
        width=image.width,
        height=image.height,
        thumb=derived(image, THUMB_MAX_EDGE, THUMB_SUFFIX),
        slim=derived(image, SLIM_MAX_EDGE, SLIM_SUFFIX),
    )


def prepared_images(uploads: list[bytes]) -> list[PreparedImage]:
    """Decode a whole post's worth of uploads, all or nothing.

    Every image is validated before any message row is written, so a refusal
    never leaves an empty message behind on the line.
    """
    if not uploads:
        raise MediaError(400, "no image was uploaded")
    if len(uploads) > MAX_IMAGES_PER_POST:
        raise MediaError(400, f"at most {MAX_IMAGES_PER_POST} images per post")
    return [prepared_image(data) for data in uploads]
