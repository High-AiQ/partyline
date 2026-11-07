"""The dialog itself, run as `<helper> dialog <request>` (or `python -m partyline_helper.dialog_proc`).

A separate process gives Tk its own main thread (macOS requires that) and lets the helper cancel a
dialog by killing it. The request is one base64 JSON argument, not stdin: a windowed (pythonw or frozen)
process may have no stdin at all. The parent's pid is in the request; when that process is gone the dialog
goes too. Exit status 0 means Yes (or OK), anything else No.
"""
import base64
import json
import os
import sys
import threading
import time

from . import foreground


def encode_request(title, message, timeout, kind="ask", parent=None):
    data = {"title": title, "message": message, "timeout": timeout, "kind": kind,
            "parent": os.getpid() if parent is None else parent}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def tk_ask(title, message, timeout, kind="ask"):
    """tkinter yes/no (or a single OK); in front of other windows; closes itself after `timeout`."""
    import tkinter
    foreground.make_dpi_aware()
    root = tkinter.Tk()
    root.title(title)
    answer = []
    tkinter.Label(root, text=message, justify="left", wraplength=420, padx=16, pady=12).pack()
    buttons = tkinter.Frame(root)
    buttons.pack(pady=(0, 12))
    for text, value in (("OK", True),) if kind == "info" else (("Yes", True), ("No", False)):
        tkinter.Button(buttons, text=text, width=10,
                       command=lambda value=value: (answer.append(value), root.destroy())).pack(
            side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.after(int(timeout * 1000), root.destroy)
    foreground.center(root)
    foreground.keep_raising(root)
    root.mainloop()
    return answer == [True]


def message_box(title, message, kind):  # pragma: no cover - Windows-only ctypes call
    import ctypes
    # MB_SETFOREGROUND | MB_TOPMOST, then a notice (info icon, OK) or a question (Yes/No, default No)
    flags = 0x10000 | 0x40000 | (0x40 if kind == "info" else 0x4 | 0x20 | 0x100)
    return ctypes.windll.user32.MessageBoxW(None, message, title, flags) in (1, 6)


def ask(title, message, timeout, kind="ask"):
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return message_box(title, message, kind) if os.name == "nt" else False
    return tk_ask(title, message, timeout, kind)


def process_gone(pid, sleep=time.sleep):
    """Block until process `pid` has exited."""
    if os.name == "nt":  # pragma: no cover - Windows only
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            raise OSError("cannot watch the helper process")  # the caller then keeps the dialog open
        ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        return
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            pass
        sleep(1)


def watch_parent(pid, exit_fn=os._exit, wait=process_gone):
    """Exit the moment the helper that opened this dialog is gone, even mid-dialog."""
    def watch():
        try:
            wait(pid)
        except Exception:  # noqa: BLE001 - cannot tell: leave the dialog alone (its own timeout closes it)
            return
        exit_fn(3)
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


def main(argv=None, watch=watch_parent):
    try:
        data = json.loads(base64.urlsafe_b64decode((sys.argv[1:] if argv is None else argv)[0]))
        watch(int(data["parent"]))
        kind = "info" if data.get("kind") == "info" else "ask"
        return 0 if ask(str(data["title"]), str(data["message"]), float(data["timeout"]), kind) else 1
    except Exception:  # noqa: BLE001 - any failure must decline, never crash into an accept
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
