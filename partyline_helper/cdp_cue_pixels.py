"""Measure where Chrome's inspector overlay really draws, from screenshots with and without a probe.

The probe is found by what changed between the two, never by its colour, so what the page itself paints
(any accent, image or animation outside the probe) cannot be mistaken for it or hide it."""
from PIL import Image, ImageChops, ImageStat

TOLERANCE = 24
LEAST, MOST = 0.5, 8.0  # screenshot pixels per overlay unit that are believable
AGREE = 0.15  # the probe's left edge and width must give the same scale, within this fraction
LIGHT, DARK = {"r": 255, "g": 255, "b": 255, "a": 1}, {"r": 0, "g": 0, "b": 0, "a": 1}


def contrast(stream, flip=False):
    """The probe colour furthest from the page's mean brightness in the clip (the other one when `flip`)."""
    mean = ImageStat.Stat(Image.open(stream).convert("L")).mean[0]
    return LIGHT if (mean >= 128) == flip else DARK


def changed(before, after):
    return ImageChops.difference(before, after).point(lambda value: 255 if value > TOLERANCE else 0)


def probe_scale(before, after, size):
    """Screenshot pixels per overlay unit for a probe drawn at (size, size) with width `size`; None when the
    probe is missing, partial or inconsistent. The screenshots are clipped at the viewport origin, so the
    probe's left edge is `size` units from its left side whatever the pixel ratio."""
    first, second = Image.open(before).convert("RGB"), Image.open(after).convert("RGB")
    if first.size != second.size:
        return None
    red, green, blue = changed(first, second).split()
    box = ImageChops.lighter(ImageChops.lighter(red, green), blue).getbbox()
    if not box:
        return None
    left, top, right, bottom = box
    from_edge, from_width = left / size, (right - left) / size
    if not (LEAST <= from_edge <= MOST) or abs(from_edge - from_width) > AGREE * from_edge:
        return None
    if abs(top - left) > 1 + AGREE * left or abs((bottom - top) - (right - left)) > 2:
        return None  # not a square at the diagonal: a different mapping on each axis
    return from_edge
