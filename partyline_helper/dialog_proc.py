"""The dialog itself, run as `python -m partyline_helper.dialog_proc`.

A separate process gives Tk its own main thread (macOS requires that) and lets the helper cancel a
dialog by killing it. Input is one JSON line on stdin; exit status 0 means Yes, anything else No. The
parent keeps stdin open, so EOF means the parent is gone and the dialog must go with it.
"""
import contextlib
import json
import os
import sys
import threading


def tk_ask(title, message, timeout):
    """tkinter yes/no; closes itself (decline) after `timeout` seconds."""
    import tkinter
    root = tkinter.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    answer = []
    tkinter.Label(root, text=message, justify="left", wraplength=420, padx=16, pady=12).pack()
    buttons = tkinter.Frame(root)
    buttons.pack(pady=(0, 12))
    for text, value in (("Yes", True), ("No", False)):
        tkinter.Button(buttons, text=text, width=10,
                       command=lambda value=value: (answer.append(value), root.destroy())).pack(
            side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.after(int(timeout * 1000), root.destroy)
    root.mainloop()
    return answer == [True]


def message_box(title, message, timeout):  # pragma: no cover - Windows-only ctypes call
    import ctypes
    # MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2 | MB_SETFOREGROUND | MB_TOPMOST; no timeout (parent kills)
    flags = 0x4 | 0x20 | 0x100 | 0x10000 | 0x40000
    return ctypes.windll.user32.MessageBoxW(None, message, title, flags) == 6


def ask(title, message, timeout):
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return message_box(title, message, timeout) if os.name == "nt" else False
    return tk_ask(title, message, timeout)


def watch_parent(stream, exit_fn=os._exit):
    """Exit the moment stdin closes (the parent died or closed us), even mid-dialog."""
    def watch():
        with contextlib.suppress(Exception):
            stream.read()
        exit_fn(3)
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


def main(stream=None, watch=watch_parent):
    try:
        stream = stream or sys.stdin
        data = json.loads(stream.readline())
        watch(stream)
        return 0 if ask(str(data["title"]), str(data["message"]), float(data["timeout"])) else 1
    except Exception:  # noqa: BLE001 - any failure must decline, never crash into an accept
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
