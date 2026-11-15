"""Make one window the foreground when another one is, without raising it above the rest of the order."""
import ctypes


def activate(user32, kernel32, hwnd, expected_current):
    """True when `hwnd` is now the foreground window. Does nothing unless `expected_current` is foreground.

    `kernel32` is a function returning the library, called only once the foreground matches.
    """
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    if not hwnd or user32.GetForegroundWindow() != expected_current:
        return False
    kernel32 = kernel32()
    kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
    current_thread = kernel32.GetCurrentThreadId()
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
    user32.AttachThreadInput.restype = ctypes.c_bool
    foreground_thread = user32.GetWindowThreadProcessId(expected_current, None)
    attached = bool(foreground_thread and foreground_thread != current_thread and
                    user32.AttachThreadInput(current_thread, foreground_thread, True))
    if user32.GetForegroundWindow() != expected_current:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        return False
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.SetWindowPos.restype = ctypes.c_bool
    # Keep the window's place in the z-order without activating until SetForegroundWindow below.
    ordered = user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_bool
    try:
        activated = user32.SetForegroundWindow(hwnd) if ordered else False
        return bool(activated and user32.GetForegroundWindow() == hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
