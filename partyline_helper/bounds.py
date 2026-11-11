"""Request validation shared by the session: numeric bounds and region-on-desktop checks."""
import math

MAX_MESSAGE_BYTES = 1_000_000  # server reference calls must fit helpers installed with this limit


def bounded(value, default, low, high):
    number = float(value if value is not None else default)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError("Share setting outside supported bounds")
    return number


def validate_request(desktop, request):
    if not getattr(desktop, "supports_capture", True):
        raise RuntimeError("Screen capture is unsupported on this platform; macOS ScreenCaptureKit and Linux "
                           "desktop capture need follow-up")
    region = request["region"]
    for key in ("x", "y", "width", "height"):
        if type(region[key]) is not int:
            raise ValueError("Region must use integer desktop pixels")
    if not 0 < region["width"] <= 32768 or not 0 < region["height"] <= 32768:
        raise ValueError("Invalid region dimensions")
    # Bound allocation and ensure all pixels belong to the virtual desktop.
    if region["width"] * region["height"] > 100_000_000:
        raise ValueError("Region is too large")
    monitors = desktop.monitors()
    left, top = min(m["x"] for m in monitors), min(m["y"] for m in monitors)
    right = max(m["x"] + m["width"] for m in monitors)
    bottom = max(m["y"] + m["height"] for m in monitors)
    if not (left <= region["x"] and top <= region["y"] and
            region["x"] + region["width"] <= right and region["y"] + region["height"] <= bottom):
        raise ValueError("Region is outside the desktop")
    request["max_fps"] = bounded(request.get("max_fps"), 1, 0.1, 30)
    request["long_edge"] = int(bounded(request.get("long_edge"), 1280, 1, 4096))
    request["min_change"] = bounded(request.get("min_change"), .02, 0, 1)
