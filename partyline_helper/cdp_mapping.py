"""Map an explicitly granted Chrome HWND to exactly one browser window and active page."""
import asyncio

from .cdp_transport import CDPError


def frame(hwnd):  # pragma: no cover - native DWM/DPI APIs, faked in portable tests
    import ctypes
    from ctypes import wintypes
    from .window_outline import WindowOutline
    bounds = WindowOutline(hwnd).frame_bounds()
    if bounds is None:
        raise CDPError("Chrome window is minimized or hidden")
    user = ctypes.windll.user32
    user.GetDpiForWindow.argtypes = [wintypes.HWND]
    user.GetDpiForWindow.restype = wintypes.UINT
    scale = user.GetDpiForWindow(hwnd) / 96
    if not scale:
        raise CDPError("Chrome window DPI unavailable")
    return tuple(value / scale for value in bounds)


def title_matches(title, window):
    return bool(title) and (window == title or window.startswith(title + " - ") and "Chrome" in window)


def same_bounds(bounds, rect):
    return all(abs(bounds.get(key, -100000) - value) <= 16
               for key, value in zip(("left", "top", "width", "height"), rect, strict=True))


async def map_window(connection, access, guard, bounds=frame, recovery_target=None):
    grant = access.grant
    if not grant or grant.get("process", "").lower() != "chrome.exe":
        raise CDPError("not a Chrome window")
    windows = await asyncio.to_thread(access.list_windows)
    guard()
    window = next((w for w in windows or [] if w["hwnd"] == grant["hwnd"] and w["pid"] == grant["pid"]), None)
    if window is None:
        raise CDPError("Chrome window closed or desktop unavailable")
    processes = await connection.call("SystemInfo.getProcessInfo", guard=guard)
    if not any(p.get("type") == "browser" and p.get("id") == grant["pid"]
               for p in processes.get("processInfo", [])):
        raise CDPError("Chrome browser process does not match the shared HWND")
    rect = await asyncio.to_thread(bounds, grant["hwnd"])
    guard()
    targets = await connection.call("Target.getTargets", guard=guard)
    groups = {}
    for target in targets.get("targetInfos", []):
        if target.get("type") != "page":
            continue
        result = await connection.call("Browser.getWindowForTarget",
                                       {"targetId": target["targetId"]}, guard=guard)
        if same_bounds(result.get("bounds", {}), rect):
            groups.setdefault(result["windowId"], []).append(target)
    candidates = [(ident, pages) for ident, pages in groups.items()
                  if any(title_matches(page.get("title", ""), window["title"]) for page in pages)]
    if not candidates and recovery_target:
        candidates = [(ident, pages) for ident, pages in groups.items()
                      if any(t["targetId"] == recovery_target for t in pages)]
    if len(candidates) != 1:
        raise CDPError("Chrome window mapping ambiguous or missing; using UIA")
    return candidates[0], window
