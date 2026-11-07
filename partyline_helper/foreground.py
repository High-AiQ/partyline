"""Bring a dialog in front of other windows from a background process.

Windows refuses `SetForegroundWindow` unless the caller owns the foreground or recent input, so a
dialog opened by the login-started helper normally lands behind the browser and only blinks. We make it
topmost, borrow the foreground thread's input queue, send a synthetic Alt tap if still refused, and as
the last resort flash the taskbar button until the person clicks it. Every Win32 call goes through the
`user32` / `kernel32` objects passed in, so the sequence is testable with fakes.
"""
import ctypes
import os

SW_SHOW, SW_RESTORE, HWND_TOPMOST = 5, 9, -1
SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x1, 0x2, 0x40
VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x2
FLASHW_ALL, FLASHW_TIMERNOFG = 0x3, 0xC


class FlashInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("dwFlags", ctypes.c_uint),
                ("uCount", ctypes.c_uint), ("dwTimeout", ctypes.c_uint)]


def flash_taskbar(hwnd, user32):
    """Flash the window's taskbar button until it is brought to the foreground."""
    info = FlashInfo(ctypes.sizeof(FlashInfo), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
    user32.FlashWindowEx(ctypes.byref(info))


def bring_to_front(hwnd, user32, kernel32):
    """True when `hwnd` is now the foreground window; otherwise its taskbar button is flashing."""
    user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    if user32.GetForegroundWindow() == hwnd:
        return True
    ours = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    attached = bool(theirs) and theirs != ours and bool(user32.AttachThreadInput(ours, theirs, True))
    try:
        user32.SetForegroundWindow(hwnd)
        if user32.GetForegroundWindow() != hwnd:
            # A synthetic key press makes this process the last input owner, which unlocks the call.
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(ours, theirs, False)
    if user32.GetForegroundWindow() == hwnd:
        return True
    flash_taskbar(hwnd, user32)
    return False


def native_libraries():  # pragma: no cover - Windows only
    return ctypes.windll.user32, ctypes.windll.kernel32


def raise_window(root, bring=bring_to_front, libraries=native_libraries, windows=None):
    """Tk window `root` to the front. Returns True when it is certain to be foreground (or not Windows)."""
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    if not (os.name == "nt" if windows is None else windows):
        root.focus_force()
        return True
    try:
        user32, kernel32 = libraries()
        hwnd = int(root.wm_frame(), 16)
        return bool(bring(hwnd, user32, kernel32))
    except (OSError, ValueError, AttributeError):
        return False


def keep_raising(root, raise_it=raise_window, tries=6, delay_ms=300):
    """Raise now and retry shortly after: the window may not be mapped on the first call."""
    left = [tries]

    def attempt():
        if raise_it(root):
            return
        left[0] -= 1
        if left[0] > 0:
            root.after(delay_ms, attempt)
    root.after(0, attempt)


def center(root):
    """Open in the middle of the screen, not wherever the OS cascade puts a background process."""
    root.update_idletasks()
    width, height = root.winfo_reqwidth(), root.winfo_reqheight()
    left = max(0, (root.winfo_screenwidth() - width) // 2)
    top = max(0, (root.winfo_screenheight() - height) // 3)
    root.geometry(f"+{left}+{top}")


def make_dpi_aware():  # pragma: no cover - Windows only
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        pass
