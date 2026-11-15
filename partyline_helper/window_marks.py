"""The overlay of a marked snapshot: a light coordinate grid and numbered boxes, in the image's own pixels."""
from PIL import Image, ImageDraw, ImageFont

from partyline.point_geometry import to_image

GRID = 100  # image pixels between grid lines
MAX_MARKS = 80
MIN_SIDE = 3  # a box thinner than this after clipping is not worth a number
COLORS = ((230, 50, 50), (30, 120, 230), (20, 150, 70), (200, 110, 0), (150, 50, 200))


def clean_inputs(marks):
    """The server's mark requests that have an id and a box of four numbers, at most MAX_MARKS."""
    found = []
    for mark in marks if isinstance(marks, list) else ():
        if (not isinstance(mark, dict) or not isinstance(mark.get("n"), int)
                or not isinstance(mark.get("id"), str)):
            continue
        for kind in ("screen", "viewport"):
            box = mark.get(kind)
            if (isinstance(box, list) and len(box) == 4
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)):
                found.append({"n": mark["n"], "id": mark["id"][:128], "role": str(mark.get("role", ""))[:20],
                              "name": str(mark.get("name", ""))[:40], kind: box})
                break
    return found[:MAX_MARKS]


def boxes(marks, geometry, page=None, min_side=MIN_SIDE):
    """`[(mark, (left, top, right, bottom))]` in image pixels, clipped to the image.

    A screen box converts with the geometry; a page box (CSS pixels of the viewport) first goes through
    `page` = (screen left, screen top, screen pixels per CSS pixel) and is dropped when that is unknown.
    """
    width, height = geometry["size"]
    found = []
    for mark in marks:
        if "screen" in mark:
            left, top, right, bottom = mark["screen"]
        elif "viewport" in mark and page:
            origin_x, origin_y, factor = page
            a, b, c, d = mark["viewport"]
            left, top = origin_x + a * factor, origin_y + b * factor
            right, bottom = origin_x + c * factor, origin_y + d * factor
        else:
            continue
        (a, b), (c, d) = to_image(geometry, left, top), to_image(geometry, right, bottom)
        box = (max(0, round(a)), max(0, round(b)), min(width, round(c)), min(height, round(d)))
        if box[2] - box[0] >= min_side and box[3] - box[1] >= min_side:
            found.append((mark, box))
    return found


def draw(image, found):
    """A copy of `image` with the grid and the boxes drawn on it; it keeps the image's `info`."""
    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    pen, font = ImageDraw.Draw(layer), ImageFont.load_default()
    for x in range(GRID, base.width, GRID):
        pen.line([(x, 0), (x, base.height)], fill=(255, 255, 255, 90))
        pen.line([(x + 1, 0), (x + 1, base.height)], fill=(0, 0, 0, 50))
    for y in range(GRID, base.height, GRID):
        pen.line([(0, y), (base.width, y)], fill=(255, 255, 255, 90))
        pen.line([(0, y + 1), (base.width, y + 1)], fill=(0, 0, 0, 50))
    for x in range(0, base.width, GRID):
        pen.rectangle([x, 0, x + 28, 10], fill=(0, 0, 0, 140))
        pen.text((x + 2, 0), str(x), fill=(255, 255, 255, 255), font=font)
    for y in range(GRID, base.height, GRID):
        pen.rectangle([0, y, 28, y + 10], fill=(0, 0, 0, 140))
        pen.text((2, y), str(y), fill=(255, 255, 255, 255), font=font)
    for mark, (left, top, right, bottom) in found:
        color = COLORS[mark["n"] % len(COLORS)]
        pen.rectangle([left, top, right - 1, bottom - 1], outline=color + (255,), width=2)
        label = str(mark["n"])
        wide = 6 * len(label) + 4
        pen.rectangle([left, top, left + wide, top + 12], fill=color + (255,))
        pen.text((left + 2, top), label, fill=(255, 255, 255, 255), font=font)
    result = Image.alpha_composite(base, layer).convert("RGB")
    result.info.update(image.info)
    return result


def listed(found):
    """What the answer lists for each box: {n, id, role, name, box}."""
    return [{"n": mark["n"], "id": mark["id"], "role": mark.get("role", ""), "name": mark.get("name", ""),
             "box": list(box)}
            for mark, box in found]
