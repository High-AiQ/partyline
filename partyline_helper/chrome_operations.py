"""Operation leases and event-driven native-port discovery."""
import asyncio
import json
from functools import wraps
from contextvars import ContextVar

from partyline.file_events import file_events
from .cdp_transport import BrowserConnection
from .extension_transport import ExtensionTransport
from .native_host import discover, endpoint_path


def preferred(changed):
    return ExtensionTransport(changed) if discover() else BrowserConnection(changed)


async def select_extension(chrome):
    browser = chrome.browser
    if chrome.auto_transport and not isinstance(browser, ExtensionTransport) and discover():
        for current in list(chrome.pages):
            chrome.invalidate(current)
        await browser.close()
        if chrome.connecting and not chrome.connecting.done():
            chrome.connecting.cancel()
            await asyncio.gather(chrome.connecting, return_exceptions=True)
        chrome.pages.clear()
        chrome.browser = ExtensionTransport(chrome.report)
    return chrome.browser


async def watch_extension(chrome, events=file_events):
    """Arm before scanning so an install/reconnect is never lost; no status polling."""
    try:
        async with events(endpoint_path()) as watcher:
            while True:
                async with chrome.transport_lock:
                    if discover():
                        browser = await select_extension(chrome)
                        if isinstance(browser, ExtensionTransport):
                            if browser.state == "refused":
                                browser.state = "not_enabled"
                            await browser.ensure()
                await watcher.wait()
    except OSError as exc:
        # Per-operation discovery still works; the tray just no longer learns of a late extension itself.
        print(f"Chrome extension watch stopped ({type(exc).__name__}); reads still look for it", flush=True)


async def watch_windows(shares):
    async with asyncio.TaskGroup() as group:
        group.create_task(shares.watch())
        group.create_task(watch_extension(shares.chrome))


_ACTIVE = ContextVar("chrome_operation", default=None)


def operation(function):
    @wraps(function)
    async def run(self, access, *args, **kwargs):
        owner = (self, asyncio.current_task())
        if _ACTIVE.get() == owner:
            return await function(self, access, *args, **kwargs)
        async with self.transport_lock:
            token = _ACTIVE.set(owner)
            try:
                result = await leased(self, access, *args, **kwargs)
                if isinstance(result, dict) and result.get("source") == "cdp":
                    result["transport"] = self.browser.transport
                return result
            finally:
                _ACTIVE.reset(token)

    async def leased(self, access, *args, **kwargs):
        if access.grant and access.grant.get("chrome_cancelled"):
            return await function(self, access, *args, **kwargs)
        browser = await select_extension(self)
        if isinstance(browser, ExtensionTransport) and not browser.socket:
            if not await browser.ensure() and self.auto_transport:
                await browser.close()
                self.browser = browser = BrowserConnection(self.report)
                browser.report("not_enabled", "Extension absent; remote debugging fallback. "
                               + browser.detail)
        if isinstance(browser, ExtensionTransport) and access.grant:
            async with browser.operation(access):
                return await function(self, access, *args, **kwargs)
        return await function(self, access, *args, **kwargs)
    return run


def audit(self, access, message, operation):
    info = {"grant": access.session.window_grant_id, "line": message.get("line_id", ""),
            "process": message.get("agent", ""), "operation": operation,
            "input_length": len(message.get("expression", message.get("value", "")) or "")}
    if message.get("action") == "set_files":
        info.update(operation="set_files", file_count=len(message.get("files", [])),
                    total_bytes=sum(f["bytes"] for f in message.get("files", [])),
                    media_ids=[f["id"] for f in message.get("files", [])])
    self.session.tools.audit.append("action", "window", str(info["process"])[:120], "chrome",
                                    json.dumps(info, separators=(",", ":")))



def chrome_label(browser, state):
    if browser.transport == "extension":
        return "extension connected" if state == "connected" else "extension disconnected"
    suffix = (" " + state.replace("_", " ")
              if state in ("awaiting_approval", "refused", "disconnected") else "")
    return "not installed" if state == "not_enabled" else "remote debugging" + suffix


def current(chrome):
    """What the server and the tray show right now, not what a freshly started helper would assume."""
    browser = chrome.browser
    return {"state": browser.state, "detail": "" if browser.state == "connected" else browser.detail,
            "transport": browser.transport}


def show_current(chrome):
    now = current(chrome)
    label = chrome_label(chrome.browser, now["state"])
    chrome.session.status.chrome = "Chrome: " + label + (f" — {now['detail']}" if now["detail"] else "")
