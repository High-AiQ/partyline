"""Development-only Tk host with native Win32 controls exposed to UIA."""
import ctypes
import tkinter as tk
from ctypes import wintypes


def main():
    root = tk.Tk()
    root.title('Partyline Tk corpus')
    root.geometry('600x450+50+50')
    root.update()
    user = ctypes.windll.user32
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                    wintypes.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = wintypes.HWND
    user.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    controls = [('Edit', 'before', 20, 0, True),
                ('Button', 'Development checkbox', 60, 3, True),
                ('Button', 'Development duplicate', 100, 0, True),
                ('Button', 'Development duplicate', 140, 0, True),
                ('Button', 'Development disabled', 180, 0, False),
                ('Button', 'Development outside', 900, 0, True)]
    for klass, name, y, style, enabled in controls:
        handle = user.CreateWindowExW(0, klass, name, 0x50000000 | style, 20, y, 200, 30,
                                      root.winfo_id(), None, None, None)
        if not handle:
            raise RuntimeError('native corpus control creation failed')
        user.EnableWindow(handle, enabled)
    root.mainloop()


if __name__ == '__main__':
    main()
