"""Per-monitor DPI awareness for one thread's window coordinates (physical pixels, like the capture)."""
import contextlib
import ctypes

PER_MONITOR_V2 = -4


@contextlib.contextmanager
def per_monitor(user):  # pragma: no cover - Windows only
    """Make this thread's GetWindowRect, WindowFromPoint and SetCursorPos agree with the captured pixels."""
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR_V2))
    try:
        yield
    finally:
        if previous:
            user.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
