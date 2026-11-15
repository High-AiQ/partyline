"""A small crosshair crop of scoped window pixels; never captures the desktop."""
from PIL import ImageDraw

from partyline.point_geometry import to_image

from .window_grab import GrabError

EDGE = 240


def marked(image, point):
    rect = image.info.get("rect")
    if (not rect or not isinstance(point, list) or len(point) != 2
            or not all(isinstance(n, int) and not isinstance(n, bool) for n in point)):
        raise GrabError("the landing point has no usable window geometry")
    geometry = {"rect": rect, "size": image.size}
    x, y = (int(n) for n in to_image(geometry, *point))
    if not (0 <= x < image.width and 0 <= y < image.height):
        raise GrabError("the window moved away from the landing point; take a fresh snapshot")
    left = max(0, min(x - EDGE // 2, image.width - EDGE))
    top = max(0, min(y - EDGE // 2, image.height - EDGE))
    crop = image.crop((left, top, min(image.width, left + EDGE), min(image.height, top + EDGE)))
    pen = ImageDraw.Draw(crop)
    x, y = x - left, y - top
    for color, width in (((255, 255, 255), 5), ((220, 0, 40), 1)):
        pen.line((x - 12, y, x + 12, y), fill=color, width=width)
        pen.line((x, y - 12, x, y + 12), fill=color, width=width)
    # This diagnostic crop is not a coordinate snapshot; it must never replace the agent's mapping.
    crop.info.clear()
    return crop
