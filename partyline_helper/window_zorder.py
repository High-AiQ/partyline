"""Keep a window outline directly above its granted window, never topmost, never activating."""
import ctypes

GW_HWNDPREV = 3
GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
HWND_TOP, HWND_TOPMOST = 0, -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
PLACE_FLAGS = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE


def root_handle(user32, window):
    """Return Tk's outer top-level HWND for a strip."""
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    child = window.winfo_id()
    return int(user32.GetAncestor(child, GA_ROOT) or child)


def seat_strips(user32, target, tk_strips):
    """Place Tk strip windows directly above ``target``."""
    return place_above(user32, target, [root_handle(user32, window) for window in tk_strips])


def is_topmost(user32, hwnd):
    get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    return bool(get_long(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def place_above(user32, target, handles):
    """Insert every strip HWND just above ``target``; return False when already there.

    The target is never moved. Strips are inserted after the first foreign window above the
    target (``GW_HWNDPREV``), so anything in front of the shared window, such as a game, a dialog or
    another browser window, also covers the outline. A strip is only moved when the run of windows
    directly above the target is not made of exactly the strips.
    """
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetWindow.restype = ctypes.c_void_p
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    strips = {int(handle) for handle in handles}
    if not strips or not user32.IsWindow(target):
        return False
    above, adjacent = target, 0
    while True:
        above = user32.GetWindow(above, GW_HWNDPREV)
        if not above or int(above) not in strips:
            break
        adjacent += 1
    if adjacent == len(strips):
        return False
    topmost = is_topmost(user32, target)
    if not above:
        after = HWND_TOPMOST if topmost else HWND_TOP
    elif not topmost and is_topmost(user32, above):
        after = HWND_TOP  # Inserting after a topmost window would make the strip topmost too.
    else:
        after = int(above)
    for handle in handles:
        user32.SetWindowPos(handle, after, 0, 0, 0, 0, PLACE_FLAGS)
    return True
