"""Which rectangle of the screen is the page of a Chrome window: the choice among candidates (portable)."""
from .cdp_transport import CDPError

VIEWPORT = ("[innerWidth, innerHeight, window.visualViewport ? visualViewport.scale : 1, "
            "window.devicePixelRatio || 1]")
TOLERANCE = 0.02  # the two axes may disagree by this fraction (rounding of the page area)
TOP = 170  # the most the browser's own controls above the page may take, in DIPs (tabs, toolbar, bars)
CHROME = ("that point is on the browser's own controls (tabs, address bar), not on the page; "
          "use screen_element_action for those")


def plural(count, noun):
    return f"{count} {noun}{'' if count == 1 else 's'}"


def read_metrics(result):
    """`(innerWidth, innerHeight, pinch zoom, devicePixelRatio)` from a Runtime.evaluate answer."""
    try:
        width, height, zoom, *rest = result["result"]["value"]
        ratio = rest[0] if rest else 1
        if min(width, height, ratio) <= 0 or zoom <= 0:
            raise ValueError
        return float(width), float(height), float(zoom), float(ratio)
    except (KeyError, TypeError, ValueError):
        raise CDPError("the page size could not be read") from None


def size_of(area):
    return area[2] - area[0], area[3] - area[1]


def usable(area):
    """Whether a rectangle read from the system is a real, non-empty area."""
    try:
        return size_of(area)[0] > 0 and size_of(area)[1] > 0
    except (TypeError, IndexError):
        return False


def holds(area, point):
    return area[0] <= point[0] < area[2] and area[1] <= point[1] < area[3]


def fits(area, metrics):
    """Whether the area is as large, in screen pixels, as the page's viewport."""
    width, height, _, ratio = metrics
    wide, high = size_of(area)
    return abs(wide - width * ratio) <= TOLERANCE * wide and abs(high - height * ratio) <= TOLERANCE * high


def describe(renderers, documents):
    text = f"found {plural(len(renderers), 'renderer window')}"
    return f"{text} and {plural(len(documents), 'page document')}" if documents else text


def choose(found, metrics, point, what):
    """The page among the candidates: the only one, else the one of the viewport's size holding the point."""
    if len(found) == 1:
        return found[0]
    sized = [area for area in found if fits(area, metrics)]
    if not sized:
        raise CDPError(f"{what}, none matching the viewport")
    if point is not None:
        sized = [area for area in sized if holds(area, point)] or None
        if sized is None:
            raise CDPError(CHROME)
    if len(sized) > 1:
        raise CDPError(f"{what}, several matching the viewport")
    return sized[0]


def verify(area, metrics):
    """`(screen left, screen top, screen pixels per CSS pixel, area)`, or the reason the page is not plain."""
    width, height, zoom, _ = metrics
    wide, high = size_of(area)
    if wide <= 0 or high <= 0:
        raise CDPError("the page size could not be read")
    factor = wide / width
    if abs(zoom - 1) > 0.01 or abs(high / height - factor) > TOLERANCE * factor:
        raise CDPError("the page is pinch-zoomed or resized; take a fresh snapshot and try again")
    return area[0], area[1], factor, area
