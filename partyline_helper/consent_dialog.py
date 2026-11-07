"""Native yes/no dialogs for a helper with no terminal (login autostart, partyline:// links).

Each dialog is its own process (see dialog_proc), so Tk owns a main thread and a cancelled or timed-out
prompt is closed rather than left open. The caller races it against an injected sleep; silence declines.
"""
import asyncio
import contextlib
import importlib.util
import os
import subprocess
import sys
import threading

from .dialog_proc import encode_request

PROMPT_DELAY = 1.0
TIMEOUT = 60


def dialog_command(request, frozen=None, executable=None):
    """Argv for the dialog child. A frozen exe cannot run `-m`, so it re-runs itself with `dialog`."""
    executable = executable or sys.executable
    if getattr(sys, "frozen", False) if frozen is None else frozen:
        return [executable, "dialog", request]
    return [executable, "-m", "partyline_helper.dialog_proc", request]


class ProcessDialog:
    """A dialog in a child process: `wait()` is True only for an explicit Yes; `close()` kills it."""

    def __init__(self, title, message, timeout, popen=subprocess.Popen, kind="ask"):
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":  # pragma: no cover - Windows flag
            options["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        # The request travels in argv (no stdin in a windowed process); the child watches our pid and
        # exits if this helper dies (e.g. is restarted after re-pairing), so no dialog outlives it.
        self.proc = popen(dialog_command(encode_request(title, message, timeout, kind)), **options)

    def wait(self):
        return self.proc.wait() == 0

    def close(self):
        if self.proc.poll() is None:
            with contextlib.suppress(OSError):
                self.proc.terminate()


def default_backend():
    """The process dialog when something can draw one (tkinter, or Windows MessageBox); else None."""
    if os.name == "nt" or importlib.util.find_spec("tkinter"):
        return ProcessDialog
    return None


def windows_console(stream):  # pragma: no cover - Windows only
    """True only for a real console. NUL (what a detached process gets as stdin) is a character device,
    so isatty() says True for it; GetConsoleMode succeeds only on a console."""
    import ctypes
    import msvcrt
    mode = ctypes.c_uint32()
    handle = msvcrt.get_osfhandle(stream.fileno())
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def interactive(stream=None, windows=None, console=windows_console):
    """True when a person can answer on a terminal; pythonw, NUL, pipes and login autostart cannot."""
    stream = sys.stdin if stream is None else stream
    try:
        if not stream or not stream.isatty():
            return False
        return bool(console(stream)) if (os.name == "nt" if windows is None else windows) else True
    except (ValueError, OSError):
        return False


def auto_dialog(background=False, terminal=None):
    """None on a terminal (keep the y/N prompt); the native dialog without one. A background run (detached
    `run --log`, login autostart, the frozen exe) never prompts on a terminal: nobody can read it."""
    return None if not background and (terminal or interactive)() else confirm


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


def notify(title, message, show=None, timeout=TIMEOUT):
    """Tell a person without a terminal why something failed (a notice they must dismiss); never raises."""
    def process_show(title, message):
        ProcessDialog(title, message, timeout, kind="info").wait()
    with contextlib.suppress(Exception):
        (show or process_show)(title, message)
