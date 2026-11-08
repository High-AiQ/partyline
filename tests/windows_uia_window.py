"""Windows UIA test fixture; all Tk objects live and die in this process."""
import ctypes
import json
import os
import tkinter as tk
from ctypes import wintypes


def main():
    root = tk.Tk()
    root.title("Partyline UIA target")
    root.geometry("400x200+100+100")
    root.update()
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                       wintypes.HINSTANCE, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    controls = [user32.CreateWindowExW(0, klass, title, 0x50000000, 10, y, 150, 30,
                                       root.winfo_id(), None, None, None)
                for klass, title, y in (("Button", "Snapshot button", 10), ("Edit", "", 50))]
    other = tk.Toplevel(root)
    other.title("Partyline UIA other")
    other.geometry("300x150+600+100")
    root.update()
    rects = [wintypes.RECT(), wintypes.RECT()]
    for hwnd, rect in zip(controls, rects, strict=True):
        if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("native test controls could not be created")
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    target = user32.GetAncestor(root.winfo_id(), 2)
    other.attributes("-topmost", True)
    other.focus_force()
    root.update()
    print(json.dumps({"hwnd": target, "pid": os.getpid(),
                      "bounds": [(r.left, r.top, r.right, r.bottom) for r in rects]}), flush=True)
    root.mainloop()


if __name__ == "__main__":
    main()
