"""Enumerate visible Windows top-level windows for local, explicit selection."""
import ctypes
import os
import uuid
from ctypes import wintypes


HARD_FLOOR = frozenset({
    "cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe", "conhost.exe",
    "openconsole.exe", "bash.exe", "wsl.exe", "wslhost.exe", "ubuntu.exe", "debian.exe",
    "mintty.exe", "putty.exe", "kitty.exe", "securecrt.exe", "ssh.exe",
    "1password.exe", "lastpass.exe", "bitwarden.exe", "keepass.exe", "keepassxc.exe",
    "dashlane.exe", "nordpass.exe", "protonpass.exe", "keeperpasswordmanager.exe",
    "enpass.exe", "roboform.exe", "passwordsafe.exe", "sticky-password.exe", "sechealthui.exe",
    "securityhealthhost.exe", "windowsdefender.exe", "smartscreen.exe",
    "credentialuibroker.exe", "consent.exe", "winlogon.exe", "logonui.exe", "lockapp.exe",
    "partylinehelper.exe", "partyline helper.exe",
    "wezterm-gui.exe", "wezterm.exe", "alacritty.exe", "hyper.exe", "tabby.exe",
})


def browser_tabs(access):
    """Optional browser hook. Providers return tab title, URL and owning HWND rows."""
    return ()


def window_providers(access=None):
    """Window sources may be extended by providers such as Chrome.tabs(access)."""
    return (windows, lambda: browser_tabs(access))


def standing_windows(access=None):
    """Enumerate safe windows and browser tabs; inactive tabs keep their owning HWND."""
    providers = window_providers(access)
    rows = providers[0]()
    if rows is None:
        return None
    result = [{**row, "id": str(row["hwnd"])} for row in rows]
    by_hwnd = {str(row.get("hwnd")): row for row in result}
    for provider in providers[1:]:
        tabs = provider()
        if tabs is None:
            return None
        for tab in tabs:
            owner = by_hwnd.get(str(tab.get("hwnd")))
            if owner is None:
                continue
            title, url = str(tab.get("title", owner["title"]))[:256], str(tab.get("url", ""))[:2048]
            result.append({**owner, "title": title, "url": url,
                           "id": str(tab.get("id") or f"{owner['hwnd']}:{url or title}")[:2048]})
    return [row for row in result if row.get("process", "").casefold() not in HARD_FLOOR]


async def discover_windows(session):
    """List safe HWNDs and enrich authorized Chrome HWNDs with Chrome.tabs(access)."""
    import asyncio

    from .uia_access import WindowAccess
    from .uia_window_identity import mark
    from .window_shares import WindowSession

    release_standing_rows(session)
    result = await asyncio.to_thread(standing_windows)
    if result is None:
        return None
    safe = []
    for row in result:
        marker = mark(row["hwnd"])
        if marker:
            safe.append({**row, "marker": marker})
    result = safe
    chrome = getattr(getattr(session, "windows", None), "chrome", None)
    if not chrome or chrome.browser.state != "connected" or not chrome.browser.socket:
        session.standing_window_rows = {str(row["id"]): row for row in result}
        return result
    try:
        for row in tuple(result):
            if row.get("process", "").casefold() != "chrome.exe":
                continue
            ident = uuid.uuid4().hex
            scoped_session = WindowSession(session, ident, lambda: None)
            scoped_session.chrome = chrome
            access = WindowAccess(scoped_session)
            access.grant = row
            access.gate.grant()
            try:
                reason = await access.check(row)
                if reason or not session.window_access_enabled:
                    continue
                tabs = await browser_tabs_for_window(access, chrome)
                for tab in tabs:
                    title = str(tab.get("title", row["title"]))[:256]
                    url = str(tab.get("url", ""))[:2048]
                    marker = mark(row["hwnd"])
                    if marker:
                        target_id = str(tab.get("target_id", ""))[:128]
                        suffix = target_id or url or title
                        result.append({**row, "marker": marker, "title": title, "url": url,
                                       "id": f"{row['hwnd']}:{suffix}"[:2048],
                                       "tab_active": bool(tab.get("active")),
                                       "target_id": target_id or None})
            finally:
                chrome.revoke(access)
                access.gate.invalidate()
    except BaseException:
        from .uia_window_identity import unmark
        for row in result:
            unmark(row)
        raise
    session.standing_window_rows = {str(row["id"]): row for row in result}
    return result


def release_standing_rows(session):
    """Drop unused lifetime markers while leaving markers transferred to grants alone."""
    rows = getattr(session, "standing_window_rows", {})
    granted = {entry.get("access").grant.get("marker")
               for entry in getattr(getattr(session, "windows", None), "grants", {}).values()
               if entry.get("access") and entry["access"].grant}
    seen = set()
    from .uia_window_identity import unmark
    for row in rows.values():
        marker = row.get("marker")
        if marker and marker not in granted and marker not in seen:
            unmark(row)
            seen.add(marker)
    session.standing_window_rows = {}


async def browser_tabs_for_window(access, chrome):
    """Provider seam matching Chrome.tabs(access); caller scopes access to one safe HWND."""
    return await chrome.tabs(access)


def elevated(process):
    """Unknown token state is excluded because an elevated or security window is hard floor."""
    class Elevation(ctypes.Structure):
        _fields_ = [("token_is_elevated", wintypes.DWORD)]

    advapi = ctypes.windll.advapi32
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel = ctypes.windll.kernel32
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
        return True
    try:
        value, size = Elevation(), wintypes.DWORD()
        return (not advapi.GetTokenInformation(token, 20, ctypes.byref(value), ctypes.sizeof(value),
                                               ctypes.byref(size))
                or bool(value.token_is_elevated))
    finally:
        kernel.CloseHandle(token)


def descendants(roots):  # pragma: no cover - Win32 process snapshot
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", ctypes.c_long), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]
    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return None
    pairs, item = [], ProcessEntry()
    item.size = ctypes.sizeof(item)
    try:
        ok = kernel.Process32FirstW(handle, ctypes.byref(item))
        if not ok:
            return None
        while ok:
            pairs.append((item.pid, item.parent))
            ok = kernel.Process32NextW(handle, ctypes.byref(item))
    finally:
        kernel.CloseHandle(handle)
    result = set(roots)
    while True:
        updated = result | {pid for pid, parent in pairs if parent in result}
        if updated == result:
            return result
        result = updated


def windows(exclude=()):  # pragma: no cover - Win32 desktop APIs, covered by Windows CI
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD, ctypes.c_void_p]
    desktop = user.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return None
    try:
        name = ctypes.create_unicode_buffer(256)
        if not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), None):
            return None
        if name.value.lower() != "default":
            return None
    finally:
        user.CloseDesktop(desktop)
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.IsIconic.argtypes = [wintypes.HWND]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
    result = []
    foreground = user.GetForegroundWindow()
    excluded = descendants(set(exclude) | {os.getpid()})
    if excluded is None:
        return []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd):
            return True
        length = min(512, user.GetWindowTextLengthW(hwnd))
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user.GetWindowTextW(hwnd, title, len(title))
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value in excluded:
            return True
        process = kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return True
        try:
            if elevated(process):
                return True
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                return True
        finally:
            kernel.CloseHandle(process)
        exe = os.path.basename(path.value)
        if exe.lower() == "partylinehelper.exe" or exe.casefold() in HARD_FLOOR:
            return True
        state = "active" if hwnd == foreground else "minimized" if user.IsIconic(hwnd) else "visible"
        result.append({"hwnd": int(hwnd), "pid": pid.value, "title": title.value[:256],
                       "process": exe[:128], "state": state})
        return True

    user.EnumWindows(visit, 0)
    return result
