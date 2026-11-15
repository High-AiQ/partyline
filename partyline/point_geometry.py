"""Pixels of one window snapshot to screen pixels, the same way on the server and in the helper.

A geometry is what the helper recorded when it took the picture: `rect` (the screen pixels the image
covers, left/top/right/bottom), `size` (the image in pixels), `scale` (image pixels per screen pixel, per
axis), `dpi`, and `regions` (the screen rectangles a click may land in: the window's client area and that
of its owned popups). Image pixels have (0, 0) at the top left.
"""
from math import floor

MAX_REGIONS = 16
LIMIT = 1_000_000


class GeometryError(ValueError):
    """The point or the geometry cannot be used; the message is for the agent."""


def _ints(value, count):
    ok = isinstance(value, (list, tuple)) and len(value) == count
    if not ok or not all(isinstance(item, int) and not isinstance(item, bool) and abs(item) <= LIMIT
                         for item in value):
        raise GeometryError("the computer sent a snapshot geometry that cannot be used")
    return [int(item) for item in value]


def clean(data):
    """A validated copy of a helper-reported geometry, or GeometryError."""
    if not isinstance(data, dict):
        raise GeometryError("the computer sent a snapshot geometry that cannot be used")
    rect, size = _ints(data.get("rect"), 4), _ints(data.get("size"), 2)
    regions = data.get("regions")
    if not isinstance(regions, list) or not regions or len(regions) > MAX_REGIONS:
        raise GeometryError("the computer sent a snapshot geometry that cannot be used")
    regions = [_ints(region, 4) for region in regions]
    if rect[2] <= rect[0] or rect[3] <= rect[1] or min(size) < 1:
        raise GeometryError("the computer sent a snapshot geometry that cannot be used")
    dpi = data.get("dpi")
    dpi = dpi if isinstance(dpi, int) and not isinstance(dpi, bool) and 0 < dpi <= 2000 else 96
    return {"rect": rect, "size": size, "dpi": dpi, "regions": regions,
            "scale": [size[0] / (rect[2] - rect[0]), size[1] / (rect[3] - rect[1])]}


def to_screen(geometry, x, y):
    """The screen pixel under image pixel (x, y); outside the image is an error, never clamped."""
    width, height = geometry["size"]
    if not (isinstance(x, int) and isinstance(y, int)) or isinstance(x, bool) or isinstance(y, bool):
        raise GeometryError("x and y must be whole image pixels")
    if not (0 <= x < width and 0 <= y < height):
        raise GeometryError(f"({x}, {y}) is outside the snapshot image ({width}x{height} pixels)")
    left, top, right, bottom = geometry["rect"]
    return (left + floor((x + 0.5) * (right - left) / width),
            top + floor((y + 0.5) * (bottom - top) / height))


def to_image(geometry, sx, sy):
    """The image pixel (float) for a screen pixel; may fall outside the image."""
    left, top, right, bottom = geometry["rect"]
    width, height = geometry["size"]
    return (sx - left) * width / (right - left), (sy - top) * height / (bottom - top)


def in_client(geometry, sx, sy):
    return any(a <= sx < c and b <= sy < d for a, b, c, d in geometry["regions"])


def locate(geometry, x, y):
    """The screen pixel for image pixel (x, y), refused unless it lies in the window's client area."""
    point = to_screen(geometry, x, y)
    if not in_client(geometry, *point):
        raise GeometryError("that point is on the window's frame or title bar, outside its client area; "
                            "use screen_element_action for window controls")
    return point
