"""Native click-through windows, always owned by a daemon worker thread."""
import contextlib
import ctypes
import gc
import queue
import sys
import threading

WINDOWS_CAPTURE_BUILD = 19041  # Windows 10 2004: WDA_EXCLUDEFROMCAPTURE
WDA_EXCLUDEFROMCAPTURE = 0x11


def native_backend(on_error):
    if sys.platform == "darwin":
        try:
            import AppKit  # noqa: F401
        except ImportError:
            raise RuntimeError("macOS border needs PyObjC; install pyobjc or use --no-border") from None
        return CocoaBackend(on_error)
    if sys.platform == "win32":
        return TkBackend(on_error, windows=True)
    if sys.platform.startswith("linux"):
        return TkBackend(on_error)
    raise RuntimeError(f"No capture border backend for {sys.platform}")


class ThreadBackend:
    """Commands are ordered, non-blocking and confined to the native GUI thread."""

    def __init__(self, on_error):
        self.on_error = on_error
        self.commands = queue.Queue()
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run_safe, name="capture-border", daemon=True)
            self.thread.start()

    def run_safe(self):
        try:
            self.run()
        except Exception as exc:
            # A retained traceback otherwise keeps make_window's Tk arguments alive for main-thread GC.
            self.on_error(exc.with_traceback(None))
            gc.collect()

    def show(self, strips, color):
        self.start()
        self.commands.put(("show", strips, color))

    def hide(self):
        if self.thread is not None:
            self.commands.put(("hide",))

    def close(self):
        if self.thread is not None:
            self.commands.put(("close",))


class TkBackend(ThreadBackend):
    """Four override-redirect strips on X11 or no-activate layered windows on Windows."""

    def __init__(self, on_error, windows=False):
        super().__init__(on_error)
        self.windows = windows

    def run(self):
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        strips = []

        def clear():
            for window in strips:
                window.destroy()
            strips.clear()

        failure = None
        try:
            while True:
                try:
                    command = self.commands.get(timeout=.02)
                except queue.Empty:
                    command = (None,)
                if command[0] == "show":
                    clear()
                    for rectangle in command[1]:
                        strips.append(self.make_window(tk, root, rectangle, command[2]))
                elif command[0] == "hide":
                    clear()
                elif command[0] == "close":
                    break
                if self.windows:
                    root.update()
                else:
                    root.update_idletasks()  # Static X11 strips need redraws, not Tcl's full notifier.
        except Exception as exc:
            failure = exc.with_traceback(None)
        finally:
            with contextlib.suppress(Exception):
                clear()
            with contextlib.suppress(Exception):
                root.destroy()
            # Release interpreter/closure cycles on their owner thread, never the sharing thread.
            root = strips = clear = None
            gc.collect()
        if failure is not None:
            self.on_error(failure)
            gc.collect()

    def make_window(self, tk, root, rectangle, color):
        x, y, width, height = (round(value) for value in rectangle)
        window = tk.Toplevel(root)
        window.withdraw()  # Apply Windows capture affinity before the first visible frame.
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(background=color, borderwidth=0, highlightthickness=0)
        # Plus signs select absolute coordinates; "+-100" preserves a negative desktop origin.
        window.geometry(f"{max(1, width)}x{max(1, height)}+{x}+{y}")
        window.update_idletasks()  # Create Tk's hidden native wrapper before configuring it.
        if self.windows:
            windows_options(window)
        else:
            x11_click_through(window)
        window.deiconify()
        return window


class XErrorEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("display", ctypes.c_void_p),
                ("resourceid", ctypes.c_ulong), ("serial", ctypes.c_ulong),
                ("error_code", ctypes.c_ubyte), ("request_code", ctypes.c_ubyte),
                ("minor_code", ctypes.c_ubyte)]


def x11_click_through(window, x11=None, xext=None):
    """Give the strip an empty input shape and turn Xlib errors into Python failures."""
    x11 = x11 or ctypes.CDLL("libX11.so.6")
    xext = xext or ctypes.CDLL("libXext.so.6")
    window.update_idletasks()  # Flush Tk's window creation on its own X connection first.
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    xext.XShapeCombineRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int]
    display = x11.XOpenDisplay(None)
    if not display:
        raise OSError("Unable to make the capture border click-through on X11")
    errors = []
    handler_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))

    @handler_type
    def error_handler(display, event):
        errors.append(event.contents.error_code)
        return 0

    previous = x11.XSetErrorHandler(ctypes.cast(error_handler, ctypes.c_void_p))
    try:
        # ShapeInput=2, ShapeSet=0, Unsorted=0: clicks fall through to the desktop.
        xext.XShapeCombineRectangles(display, window.winfo_id(), 2, 0, 0, None, 0, 0, 0)
        x11.XSync(display, False)  # X errors are asynchronous and otherwise exit the process.
    finally:
        x11.XSetErrorHandler(previous)
        x11.XCloseDisplay(display)
    if errors:
        raise OSError(f"X11 refused the border input shape (error {errors[0]})")


def windows_options(window, windll=None, build=None):
    """Make a Tk HWND click-through/topmost and exclude it on supported Windows."""
    windll = windll or ctypes.windll
    user32 = windll.user32
    child = window.winfo_id()
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    hwnd = user32.GetAncestor(child, 2) or child  # GA_ROOT: Tk's outer top-level wrapper
    get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
    get_long.restype = ctypes.c_long
    set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    set_long.restype = ctypes.c_long
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    extended = get_long(hwnd, -20)  # GWL_EXSTYLE
    flags = 0x00080000 | 0x00000020 | 0x00000080 | 0x00000008 | 0x08000000
    set_long(hwnd, -20, extended | flags)
    user32.SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                                  ctypes.c_ubyte, ctypes.c_uint]
    user32.SetLayeredWindowAttributes.restype = ctypes.c_bool
    if not user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2):  # LWA_ALPHA, fully opaque
        raise OSError("Windows refused to initialize the layered capture border")
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0040)
    build = sys.getwindowsversion().build if build is None else build
    if build >= WINDOWS_CAPTURE_BUILD:
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            raise OSError("Windows refused to exclude the border from screen capture")


def cocoa_frame(rectangle, primary_height):
    """Convert a top-left-origin rectangle to AppKit's bottom-left coordinates."""
    x, y, width, height = rectangle
    return x, primary_height - y - height, width, height


class CocoaBackend(ThreadBackend):
    """Borderless, mouse-ignoring NSWindows on a private AppKit run loop."""

    def run(self):
        import AppKit

        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(1)  # accessory: no Dock icon or application focus
        windows = []
        try:
            running = True
            while running:
                try:
                    command = self.commands.get(timeout=.05)
                    if command[0] == "show":
                        self.cocoa_clear(windows)
                        height = AppKit.NSScreen.screens()[0].frame().size.height
                        color = self.cocoa_color(AppKit, command[2])
                        for rectangle in command[1]:
                            windows.append(self.cocoa_window(AppKit, cocoa_frame(rectangle, height), color))
                    elif command[0] == "hide":
                        self.cocoa_clear(windows)
                    else:
                        running = False
                except queue.Empty:
                    pass
                AppKit.NSRunLoop.currentRunLoop().runMode_beforeDate_(
                    AppKit.NSDefaultRunLoopMode, AppKit.NSDate.dateWithTimeIntervalSinceNow_(0))
        finally:
            self.cocoa_clear(windows)

    @staticmethod
    def cocoa_clear(windows):
        for window in windows:
            window.orderOut_(None)
            window.close()
        windows.clear()

    @staticmethod
    def cocoa_color(AppKit, value):
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        return AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*channels, 1)

    @staticmethod
    def cocoa_window(AppKit, rectangle, color):
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(*rectangle), AppKit.NSBorderlessWindowMask,
            AppKit.NSBackingStoreBuffered, False)
        window.setBackgroundColor_(color)
        window.setIgnoresMouseEvents_(True)
        window.setLevel_(AppKit.NSScreenSaverWindowLevel)
        window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                      AppKit.NSWindowCollectionBehaviorStationary)
        window.setHasShadow_(False)
        window.setReleasedWhenClosed_(False)
        window.orderFrontRegardless()
        return window
