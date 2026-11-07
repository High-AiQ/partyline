"""Fail-open capture-zone border with a small mode API for future input control."""
import math
import threading

from .border_native import native_backend

BORDER_THICKNESS = 4
MODE_COLORS = {"share": "#f6c344", "control": "#ef4444"}


def outside_strips(region, thickness=BORDER_THICKNESS, scale=1.0):
    """Return top, bottom, left and right rectangles outside a top-left-origin region."""
    if not math.isfinite(scale) or scale <= 0 or thickness <= 0:
        raise ValueError("Border scale and thickness must be positive")
    x, y, width, height = (region[key] for key in ("x", "y", "width", "height"))
    left, top = x - thickness, y - thickness
    outer_width = width + 2 * thickness
    rectangles = (
        (left, top, outer_width, thickness),
        (left, y + height, outer_width, thickness),
        (left, y, thickness, height),
        (x + width, y, thickness, height),
    )

    def points(value):
        return value if scale == 1 else value / scale

    return [tuple(points(value) for value in rectangle) for rectangle in rectangles]


class CaptureBorder:
    """Own one native backend; every backend operation is safe to fail."""

    def __init__(self, scale=1.0, backend_factory=None, warning=None):
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("Border scale must be positive")
        self.scale = scale
        self.mode = "share"
        self.region = None
        self.backend = None
        self.backend_factory = backend_factory or native_backend
        self.warning = warning or (lambda message: print(message, flush=True))
        self.failed = self.closed = False
        self.warning_lock = threading.Lock()

    def fail(self, error):
        """Report a native failure once; sharing must continue without the overlay."""
        with self.warning_lock:
            if self.failed:
                return
            self.failed = True
        detail = " ".join(str(error).splitlines()) or error.__class__.__name__
        self.warning(f"Capture border unavailable; sharing continues: {detail}")

    def get_backend(self):
        if self.backend is None:
            self.backend = self.backend_factory(self.fail)
        return self.backend

    def show(self, region):
        if self.failed or self.closed:
            return
        self.region = {key: region[key] for key in ("x", "y", "width", "height")}
        try:
            strips = outside_strips(self.region, scale=self.scale)
            self.get_backend().show(strips, MODE_COLORS[self.mode])
        except Exception as exc:
            self.fail(exc)

    def set_mode(self, mode):
        """Switch between the sharing amber and future agent-control red."""
        if mode not in MODE_COLORS:
            raise ValueError("Border mode must be 'share' or 'control'")
        self.mode = mode
        if self.region is not None:
            self.show(self.region)

    def hide(self):
        self.region = None
        if self.backend is None:
            return
        try:
            self.backend.hide()
        except Exception as exc:
            self.fail(exc)

    def close(self):
        if self.closed:
            return
        self.hide()
        self.closed = True
        if self.backend is not None:
            try:
                self.backend.close()
            except Exception as exc:
                self.fail(exc)
