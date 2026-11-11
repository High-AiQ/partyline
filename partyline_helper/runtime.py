"""What a windowless `run` needs beyond the protocol: stop requests, the tray, and visible errors."""
import asyncio
import importlib
import os

from . import consent_dialog
from .stopping import watch_stop

NOT_PAIRED = ("Partyline Helper is installed but not paired yet.\n\nIn Partyline, open “Computers / Share "
              "screen”, choose “Pair a computer”, then click “Pair with installed helper”.")
RUNNING = "Partyline Helper is already running. Look for its round icon in the system tray (near the clock)."


def tray_wanted(no_tray, windows=None):
    """The tray icon is on by default on Windows, where the helper otherwise has no visible presence."""
    return not no_tray and (os.name == "nt" if windows is None else windows)


def fail(message, interactive=None, tell=None):
    """Print for a terminal; show a dialog when there is none (windowed exe, login autostart)."""
    print(message)
    if not (interactive or consent_dialog.interactive)():
        (tell or consent_dialog.notify)("Partyline Helper", message)


async def guarded(work, status, watch=watch_stop):
    """Run the helper until it ends, is cancelled by a stop request, or the tray's Quit."""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(work)
    status.quit = lambda: loop.call_soon_threadsafe(task.cancel)
    watcher = asyncio.ensure_future(watch(task.cancel))
    try:
        await task
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise  # Ctrl+C, not a stop request
        print("Helper stopped.", flush=True)
    finally:
        watcher.cancel()


def start_helper(paired, ensure, tell=None):
    """Double-click / Start menu: start the helper if needed, and say so when there is nothing to start."""
    tell = tell or consent_dialog.notify
    if not paired():
        tell("Partyline Helper", NOT_PAIRED)
        return NOT_PAIRED
    result = ensure()
    if "already running" in result:
        tell("Partyline Helper", RUNNING)
    return result


CHECKED = ("partyline_helper.client", "partyline_helper.desktop", "partyline_helper.inputs",
           "partyline_helper.border", "partyline_helper.tray", "partyline_helper.dialog_proc",
           "partyline_helper.capture_loop", "partyline_helper.windows_capture",
           "websockets.asyncio.client", "pynput.keyboard", "pynput.mouse", "pystray", "PIL.ImageDraw")
WINDOWS_CHECKED = ("comtypes.client", "comtypes.gen.UIAutomationClient", "windows_capture")


def selfcheck(modules=CHECKED, load=importlib.import_module, windows=None, initialize=None):
    """Problems that would break a frozen build: missing modules, Tcl/Tk files, WebP. [] when all is well."""
    problems = []
    if modules is CHECKED and (os.name == "nt" if windows is None else windows):
        try:
            if initialize is None:
                from .uia_process import initialize
            initialize()
        except Exception as exc:  # noqa: BLE001 - report broken type library generation
            problems.append(f"UIAutomationClient: {exc.__class__.__name__}: {exc}")
        modules += WINDOWS_CHECKED
    for name in modules:
        try:
            load(name)
        except Exception as exc:  # noqa: BLE001 - report whatever failed to import
            problems.append(f"{name}: {exc.__class__.__name__}: {exc}")
    try:
        import tkinter
        tkinter.Tcl().eval("info patchlevel")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"tkinter: {exc.__class__.__name__}: {exc}")
    try:
        from PIL import features
        if not features.check("webp"):
            problems.append("Pillow was built without WebP")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"Pillow: {exc.__class__.__name__}: {exc}")
    return problems
