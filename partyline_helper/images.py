"""Bounded image encoding and change detection."""
from io import BytesIO

from PIL import ImageChops, ImageStat

MAX_BYTES = 4_000_000


def thumbnail(image):
    return image.convert("L").resize((64, 36))


def changed(previous, current, threshold):
    return (previous is None or
            ImageStat.Stat(ImageChops.difference(previous, current)).mean[0] / 255 > threshold)


def encode(image, long_edge):
    image = image.convert("RGB")
    image.thumbnail((long_edge, long_edge))
    while True:
        output = BytesIO()
        try:
            image.save(output, "WEBP", quality=75)
            mime = "image/webp"
        except (OSError, ValueError, KeyError):
            output = BytesIO()
            image.save(output, "JPEG", quality=75)
            mime = "image/jpeg"
        if output.tell() <= MAX_BYTES:
            return output.getvalue(), image.width, image.height, mime
        if max(image.size) <= 1:
            raise ValueError("Unable to encode within the image size cap")
        image = image.resize((max(1, image.width // 2), max(1, image.height // 2)))
