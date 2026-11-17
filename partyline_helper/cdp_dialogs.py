"""Point CDP readers to safe native dialogs owned by their granted Chrome HWND."""
import asyncio
import ctypes
import sys

from .uia_popups import WindowScope, configure
from .uia_window_list import HARD_FLOOR, windows


def native_scope(hwnd):  # pragma: no cover - Win32 ABI
    user = ctypes.windll.user32
    configure(user)
    return WindowScope(user, hwnd)


def dialog_pointer(grant, platform=sys.platform, list_windows=windows, scope_factory=native_scope):
    if platform != "win32":
        return None
    rows = list_windows()
    if rows is None:  # secure desktop: do not disclose even window metadata
        return None
    scope = scope_factory(grant["hwnd"])
    if scope.pid != grant["pid"]:
        return None
    found = []
    for row in rows[:1000]:
        hwnd = row["hwnd"]
        if (hwnd == grant["hwnd"] or row.get("process", "").casefold() in HARD_FLOOR
                or scope.class_name(hwnd) != "#32770" or not scope.accepts(hwnd)):
            continue
        title = " ".join(str(row.get("title", "Native dialog")).split())[:120]
        found.append(f'{title} (window="{hwnd}")')
        if len(found) == 4:
            break
    if not found:
        return None
    return ("Chrome owns a native dialog outside the CDP page: " + "; ".join(found)
            + '. Call screen_windows first, then screen_attach_window(window="<hwnd>") '
            "with the dialog's returned id (or share the dialog from the helper), "
            "then screen_elements(query='File name') "
            "to read its UIA controls under the same window-access consent and safety rules.")


async def with_dialog_pointer(chrome, access, result):
    """Point a CDP read at a safe native dialog the Chrome window owns (CDP cannot see it)."""
    if result is not None and not result.get("page_dialog"):
        page = chrome.pages[access][chrome.selected[access]]
        pointer = await asyncio.to_thread(chrome.dialogs, access.grant)
        page.guard()
        if pointer:
            result["source_reason"] = pointer
    return result
