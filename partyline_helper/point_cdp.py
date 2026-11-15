"""The CDP route of a point click: the page gets mouse events; no cursor moves and no window comes forward."""
import asyncio

from .cdp_transport import CDPError
from .page_area import CHROME, VIEWPORT, choose, describe, read_metrics, verify, window_area
from .page_windows import PageSources

BUTTONS = {"left": 1, "right": 2}


async def window_bounds(page, hwnd, metrics, sources):
    """The page area from the browser's own idea of the window (CDP bounds), or None."""
    try:
        bounds = (await page.call("Browser.getWindowForTarget", {})).get("bounds")
        scale = await asyncio.to_thread(sources.scale, hwnd)
    except (CDPError, OSError, AttributeError):
        return None
    return window_area(bounds, scale, metrics) if isinstance(bounds, dict) and scale else None


async def page_frame(page, hwnd, point=None, sources=None):
    """`(screen left, screen top, screen pixels per CSS pixel, area)` of the page's viewport.

    The page area is the only visible renderer window of the Chrome window; of several, the one of the
    viewport's size that holds `point`. When Chrome has none, it is the UIA Document of the active tab, or
    else what the window's CDP bounds and the page's metrics give. The same checks apply to every source."""
    sources = sources or PageSources()
    reply = await page.call("Runtime.evaluate", {"expression": VIEWPORT, "returnByValue": True})
    metrics = read_metrics(reply)
    renderers = await asyncio.to_thread(sources.renderers, hwnd)
    documents = [] if renderers else await asyncio.to_thread(sources.documents, hwnd)
    what = describe(renderers, documents)
    if renderers or documents:
        return verify(choose(renderers or documents, metrics, point, what), metrics)
    area = await window_bounds(page, hwnd, metrics, sources)
    if area is None:
        raise CDPError(f"{what} and no page document")
    return verify(area, metrics)


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
