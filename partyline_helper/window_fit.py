"""The thumb tier of a snapshot: the window shrunk to a pixel budget before anything is drawn on it.

Shrinking comes first so the numbered boxes stay legible and the geometry the helper records (its `size`)
describes the very image the agent reads: a point in that image converts back to the right screen pixel.
"""
from PIL import Image

MAX_EDGE = 4096


def budget(message):
    """`(longest side, most pixels)` from a server request, or None for the window's own size."""
    fit = message.get("fit")
    if not isinstance(fit, dict):
        return None
    edge, pixels = fit.get("edge"), fit.get("pixels")
    if all(isinstance(n, int) and not isinstance(n, bool) and 0 < n for n in (edge, pixels)):
        return min(edge, MAX_EDGE), pixels
    return None


def fitted(image, limits):
    """`image` shrunk to fit `limits`, with its `info` (screen rectangle, regions, dpi) carried over."""
    if not limits:
        return image
    edge, pixels = limits
    scale = min(1.0, edge / max(image.size), (pixels / (image.width * image.height)) ** 0.5)
    if scale >= 1.0:
        return image
    small = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                         Image.LANCZOS)
    small.info.update(image.info)
    return small
