"""The CDP route of a point click: the page gets mouse events; no cursor moves and no window comes forward."""
import asyncio

from .cdp_transport import CDPError
from .page_area import CHROME, VIEWPORT, choose, describe, fits, read_metrics, usable, verify
from .page_windows import PageSources

BUTTONS = {"left": 1, "right": 2}


async def page_frame(page, hwnd, point=None, sources=None):
    """`(screen left, screen top, screen pixels per CSS pixel, area)` of the page's viewport.

    The page area is the only visible renderer window of the Chrome window; of several, the one of the
    viewport's size that holds `point`. When Chrome has none, it is the UIA Document of the active tab, of the
    viewport's size. Anything else is refused: the window's CDP bounds give the page's size, never its place.
    The same checks apply to every source."""
    sources = sources or PageSources()
    reply = await page.call("Runtime.evaluate", {"expression": VIEWPORT, "returnByValue": True})
    metrics = read_metrics(reply)
    renderers = await asyncio.to_thread(sources.renderers, hwnd)
    if renderers:
        return verify(choose(renderers, metrics, point, describe(renderers, [])), metrics)
    found = await asyncio.to_thread(sources.documents, hwnd)
    documents = [area for area in found if usable(area)]
    what = describe(renderers, documents)
    sized = [area for area in documents if fits(area, metrics)]  # a document must be the viewport's size
    if sized:
        return verify(choose(sized, metrics, point, what), metrics)
    raise CDPError(f"{what}, none matching the viewport" if documents else f"{what} and no page document")


def to_page(frame, sx, sy):
    """CSS pixels of the viewport under a screen pixel, or an error when it is not on the page."""
    left, top, factor, area = frame
    if not (area[0] <= sx < area[2] and area[1] <= sy < area[3]):
        raise CDPError(CHROME)
    return (sx - left) / factor, (sy - top) / factor


async def click(page, frame, point, button, clicks, guard=lambda: None):
    """Move, press and release `clicks` times at the screen pixel `point` through the page's own input.

    `guard` may refuse (raise CDPError) before the move and before each press. When a press may have reached
    the page but its answer failed, a release is still attempted (the page's own call refuses it once access
    is revoked) and the error says whether it went through; it is never reported as released when unknown."""
    x, y = to_page(frame, *point)
    base = {"x": x, "y": y, "button": button, "buttons": 0}
    guard()
    await page.call("Input.dispatchMouseEvent", {**base, "type": "mouseMoved", "button": "none"})
    for count in range(1, clicks + 1):
        guard()
        try:
            await page.call("Input.dispatchMouseEvent", {**base, "type": "mousePressed", "clickCount": count,
                                                         "buttons": BUTTONS[button]})
        except CDPError as exc:  # the press may have been delivered although its answer failed
            raise CDPError(f"{exc}; {await release(page, base, count)}") from exc
        await page.call("Input.dispatchMouseEvent", {**base, "type": "mouseReleased", "clickCount": count})
    return {"page_point": [round(x, 1), round(y, 1)]}


async def release(page, base, count):
    """Best-effort release after a press whose answer failed; says what is known about the button."""
    try:
        await page.call("Input.dispatchMouseEvent", {**base, "type": "mouseReleased", "clickCount": count})
    except CDPError:
        return "the button release could not be confirmed, so a button may still be down"
    return "the button was released"
