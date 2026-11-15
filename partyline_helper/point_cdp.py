"""The CDP route of a point click: the page gets mouse events; no cursor moves and no window comes forward."""
import asyncio

from .cdp_transport import CDPError

RENDERER = "Chrome_RenderWidgetHostHWND"
VIEWPORT = "[innerWidth, innerHeight, window.visualViewport ? visualViewport.scale : 1]"
TOLERANCE = 0.02  # the two axes may disagree by this fraction (rounding of the page area)
BUTTONS = {"left": 1, "right": 2}
CHROME = ("that point is on the browser's own controls (tabs, address bar), not on the page; "
          "use screen_element_action for those")


def render_rect(hwnd):  # pragma: no cover - Windows only
    """The screen rectangle of the page area of one Chrome window, or None unless it is exactly one."""
    import ctypes
    from ctypes import wintypes
    from .window_dpi import per_monitor
    user = ctypes.windll.user32
    found = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(child, _):
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(child, name, len(name))
        if name.value == RENDERER and user.IsWindowVisible(child) and user.GetAncestor(child, 2) == hwnd:
            rect = wintypes.RECT()
            if user.GetWindowRect(child, ctypes.byref(rect)):
                found.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    with per_monitor(user):
        user.EnumChildWindows(hwnd, callback(visit), 0)
    return found[0] if len(found) == 1 else None


async def page_frame(page, hwnd, rect_of=render_rect):
    """`(screen left, screen top, screen pixels per CSS pixel, area)` of the page's viewport."""
    area = await asyncio.to_thread(rect_of, hwnd)
    if area is None:
        raise CDPError("the page area of the Chrome window could not be found")
    result = await page.call("Runtime.evaluate", {"expression": VIEWPORT, "returnByValue": True})
    try:
        width, height, zoom = result["result"]["value"]
        wide, high = area[2] - area[0], area[3] - area[1]
        factor = wide / width
        if width <= 0 or height <= 0 or wide <= 0 or high <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        raise CDPError("the page size could not be read") from None
    if abs(zoom - 1) > 0.01 or abs(high / height - factor) > TOLERANCE * factor:
        raise CDPError("the page is pinch-zoomed or resized; take a fresh snapshot and try again")
    return area[0], area[1], factor, area


def to_page(frame, sx, sy):
    """CSS pixels of the viewport under a screen pixel, or an error when it is not on the page."""
    left, top, factor, area = frame
    if not (area[0] <= sx < area[2] and area[1] <= sy < area[3]):
        raise CDPError(CHROME)
    return (sx - left) / factor, (sy - top) / factor


async def click(page, frame, point, button, clicks, guard=lambda: None):
    """Move, press and release `clicks` times at the screen pixel `point` through the page's own input.

    `guard` may refuse (raise CDPError) before the move and before each press; a button that was pressed is
    always released, unguarded."""
    x, y = to_page(frame, *point)
    base = {"x": x, "y": y, "button": button, "buttons": 0}
    guard()
    await page.call("Input.dispatchMouseEvent", {**base, "type": "mouseMoved", "button": "none"})
    for count in range(1, clicks + 1):
        guard()
        await page.call("Input.dispatchMouseEvent", {**base, "type": "mousePressed", "clickCount": count,
                                                     "buttons": BUTTONS[button]})
        await page.call("Input.dispatchMouseEvent", {**base, "type": "mouseReleased", "clickCount": count})
    return {"page_point": [round(x, 1), round(y, 1)]}
