"""Windows UIA test fixture; all Tk objects live and die in this process."""
import ctypes
import json
import os
import queue
import sys
import threading
import tkinter as tk
from ctypes import wintypes


def rect_of(user32, hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return [rect.left, rect.top, rect.right, rect.bottom]


def add_pattern_controls(user32, parent):
    """A scrollable list box, a combo box that expands and a trackbar, all native Win32 controls."""
    class CommonControls(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("classes", wintypes.DWORD)]
    ctypes.windll.comctl32.InitCommonControlsEx(ctypes.byref(CommonControls(8, 0x4)))  # trackbar class
    child, vscroll = 0x50000000, 0x00200000

    def create(klass, style, x, y, width, height):
        hwnd = user32.CreateWindowExW(0, klass, "", child | style, x, y, width, height, parent,
                                      None, None, None)
        if not hwnd:
            raise RuntimeError(f"could not create {klass}")
        return hwnd

    def text(hwnd, message, value):
        buffer = ctypes.create_unicode_buffer(value)
        user32.SendMessageW(hwnd, message, 0, ctypes.cast(buffer, ctypes.c_void_p).value)
    listbox = create("ListBox", 0x1 | vscroll | 0x00800000, 170, 10, 200, 90)  # LBS_NOTIFY
    combo = create("ComboBox", 0x3 | vscroll, 170, 110, 200, 150)  # CBS_DROPDOWNLIST
    trackbar = create("msctls_trackbar32", 0, 170, 150, 200, 30)
    for number in range(40):
        text(listbox, 0x0180, f"Item {number}")  # LB_ADDSTRING
    for number in range(4):
        text(combo, 0x0143, f"Choice {number}")  # CB_ADDSTRING
    user32.SendMessageW(combo, 0x014E, 0, 0)  # CB_SETCURSEL
    user32.SendMessageW(trackbar, 0x0406, 1, 100 << 16)  # TBM_SETRANGE 0..100
    user32.SendMessageW(trackbar, 0x0405, 1, 10)  # TBM_SETPOS
    return {"listbox": listbox, "combo": combo, "trackbar": trackbar}


def main():
    root = tk.Tk()
    root.title("Partyline UIA target")
    root.geometry("640x320+100+100")
    root.update()
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                       wintypes.HINSTANCE, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    controls = [user32.CreateWindowExW(0, klass, title, 0x50000000 | style, 10, y, 150, 30,
                                       root.winfo_id(), None, None, None)
                for klass, title, y, style in (("Button", "Snapshot button", 10, 0),
                                                ("Edit", "", 50, 0),
                                                ("Button", "Snapshot checkbox", 90, 3))]
    clicked = [0]
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    original = [None]
    @callback_type
    def window_proc(hwnd, msg, wparam, lparam):
        if msg == 0x111 and lparam == controls[0] and (wparam >> 16) == 0:
            clicked[0] += 1
        return user32.CallWindowProcW(original[0], hwnd, msg, wparam, lparam)
    original[0] = user32.SetWindowLongPtrW(root.winfo_id(), -4, ctypes.cast(window_proc, ctypes.c_void_p))
    if not original[0]:
        raise RuntimeError("could not install fixture window procedure")
    rects = [wintypes.RECT() for _ in controls]
    for hwnd, rect in zip(controls, rects, strict=True):
        if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("native test controls could not be created")
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    target = user32.GetAncestor(root.winfo_id(), 2)
    extra = add_pattern_controls(user32, root.winfo_id())
    print(json.dumps({"hwnd": target, "pid": os.getpid(),
                      "bounds": [(r.left, r.top, r.right, r.bottom) for r in rects],
                      "extra": {name: rect_of(user32, hwnd) for name, hwnd in extra.items()}}), flush=True)
    requests = queue.Queue()
    threading.Thread(target=lambda: [requests.put(line) for line in sys.stdin], daemon=True).start()
    def report():
        while not requests.empty():
            requests.get_nowait()
            value = ctypes.create_unicode_buffer(501)
            user32.GetWindowTextW(controls[1], value, len(value))
            print(json.dumps({"clicked": clicked[0], "value": value.value,
                              "checked": user32.SendMessageW(controls[2], 0x00F0, 0, 0),
                              "listbox_selected": user32.SendMessageW(extra["listbox"], 0x0188, 0, 0),
                              "listbox_top": user32.SendMessageW(extra["listbox"], 0x018E, 0, 0),
                              "combo_dropped": user32.SendMessageW(extra["combo"], 0x0157, 0, 0),
                              "trackbar": user32.SendMessageW(extra["trackbar"], 0x0400, 0, 0)}),
                  flush=True)
        root.after(10, report)
    root.after(10, report)
    root.mainloop()


def foreground():
    root = tk.Tk()
    root.title("Partyline UIA foreground")
    root.geometry("300x150+600+100")
    root.attributes("-topmost", True)
    root.focus_force()
    root.update()
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    print(json.dumps({"hwnd": user32.GetAncestor(root.winfo_id(), 2), "pid": os.getpid()}), flush=True)
    root.mainloop()


if __name__ == "__main__":
    if sys.argv[1:] == ["--role", "foreground"]:
        foreground()
    else:
        main()
