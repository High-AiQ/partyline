"""Native yes/no dialogs for a helper with no terminal (login autostart, partyline:// links).

Each dialog is its own process (see dialog_proc), so Tk owns a main thread and a cancelled or timed-out
prompt is closed rather than left open. The caller races it against an injected sleep; silence declines.
"""
import asyncio
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import threading

PROMPT_DELAY = 1.0
TIMEOUT = 60


class ProcessDialog:
    """A dialog in a child process: `wait()` is True only for an explicit Yes; `close()` kills it."""

    def __init__(self, title, message, timeout, popen=subprocess.Popen):
        options = {"stdin": subprocess.PIPE, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":  # pragma: no cover - Windows flag
            options["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        self.proc = popen([sys.executable, "-m", "partyline_helper.dialog_proc"], **options)
        # The pipe stays open: if this helper dies (e.g. is restarted after re-pairing) the child sees EOF
        # on stdin and exits, so no dialog outlives its helper.
        with contextlib.suppress(OSError):
            self.proc.stdin.write(json.dumps({"title": title, "message": message,
                                              "timeout": timeout}).encode() + b"\n")
            self.proc.stdin.flush()

    def wait(self):
        return self.proc.wait() == 0

    def close(self):
        if self.proc.poll() is None:
            with contextlib.suppress(OSError):
                self.proc.terminate()
        with contextlib.suppress(OSError):
            self.proc.stdin.close()


def default_backend():
    """The process dialog when something can draw one (tkinter, or Windows MessageBox); else None."""
    if os.name == "nt" or importlib.util.find_spec("tkinter"):
        return ProcessDialog
    return None


def interactive():
    """True when a person can answer on a terminal; pythonw and login autostart have no stdin."""
    stream = sys.stdin
    try:
        return bool(stream and stream.isatty())
    except (ValueError, OSError):
        return False


def auto_dialog():
    """None on a terminal (keep the y/N prompt); the native dialog when launched without one."""
    return None if interactive() else confirm


async def confirm(title, message, timeout=TIMEOUT, backend=None, sleep=asyncio.sleep):
    """Ask once; True only on an explicit Yes within `timeout`. Errors, silence and cancel decline.

    `backend(title, message, timeout)` returns a handle with blocking `wait()` and `close()`; the
    handle is always closed on the way out, so a dismissed prompt never leaves a window behind.
    """
    backend = backend or default_backend()
    if backend is None:
        return False
    await sleep(min(PROMPT_DELAY, timeout))  # same guard as the terminal: ignore stray early input
    loop = asyncio.get_running_loop()
    result = loop.create_future()
    try:
        handle = backend(title, message, max(0, timeout - PROMPT_DELAY))
    except Exception:  # noqa: BLE001 - no display, spawn failure: decline
        return False

    def ask():
        answer = False
        with contextlib.suppress(Exception):
            answer = handle.wait() is True
        with contextlib.suppress(RuntimeError):  # loop closed after a timeout
            loop.call_soon_threadsafe(lambda: result.done() or result.set_result(answer))

    waiting = None
    try:
        threading.Thread(target=ask, daemon=True).start()
        waiting = asyncio.ensure_future(sleep(max(0, timeout - PROMPT_DELAY)))
        await asyncio.wait({result, waiting}, return_when=asyncio.FIRST_COMPLETED)
        return result.done() and result.result() is True
    finally:
        if waiting:
            waiting.cancel()
        with contextlib.suppress(Exception):
            handle.close()


def notify(title, message, show=None):
    """Tell a person without a terminal why a link did nothing; never raises."""
    def tk_show(title, message):
        from tkinter import Tk, messagebox
        root = Tk()
        root.withdraw()
        messagebox.showinfo(title, message, parent=root)
        root.destroy()
    with contextlib.suppress(Exception):
        (show or tk_show)(title, message)
