"""Operation leases and event-driven native-port discovery."""
import asyncio
import contextlib
import json
from functools import wraps
from contextvars import ContextVar

from partyline.file_events import file_events
from .cdp_transport import BrowserConnection
from .extension_transport import ExtensionTransport
from .native_host import discover, endpoint_path, seen

PATIENCE = 3  # seconds one read waits for a returning extension, once per outage


def known():
    """The extension is running now or has run before. Only an extension never seen leaves remote debugging
    as the default; a known one that is between hosts is waited for, never replaced."""
    return bool(discover() or seen())


def preferred(changed):
    return ExtensionTransport(changed) if known() else BrowserConnection(changed)


async def await_extension(browser, events=file_events, deadline=asyncio.timeout, patience=PATIENCE):
    """Give a returning extension one brief chance to connect, woken by its host's endpoint file.

    no-poll (b): one deadline per outage; the wake is a file event, never a timer tick. A later read in
    the same outage goes straight to UIA with the reconnecting reason."""
    if browser.waited:
        return False
    browser.waited = True
    try:
        async with deadline(patience), events(endpoint_path()) as watcher:
            while True:
                browser.new_host()  # a new host is a new chance, as in watch_extension
                if await browser.ensure():
                    break
                await watcher.wait()
    except TimeoutError:
        return False
    return True


async def select_extension(chrome):
    browser = chrome.browser
    # A live host replaces remote debugging; a known extension between hosts does too unless remote debugging
    # is serving a grant right now.
    if (chrome.auto_transport and not isinstance(browser, ExtensionTransport)
            and (discover() or (known() and not browser.socket))):
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
                            browser.new_host()
                            await browser.ensure()
                await watcher.wait()
    except OSError as exc:
        # Per-operation discovery still works; the tray just no longer learns of a late extension itself.
        print(f"Chrome extension watch stopped ({type(exc).__name__}); reads still look for it", flush=True)


def keep_watching(chrome):
    """The endpoint watch is its own task, so a failing window watch (a desktop switch) cannot cancel it, and
    a watch that stopped (an OS notification error) is armed again by the next operation, never left dead."""
    watch = chrome.extension_watch
    if watch is None or not watch.done():
        return
    chrome.extension_watch = asyncio.ensure_future(watch_extension(chrome))


async def watch_windows(shares):
    chrome = shares.chrome
    chrome.extension_watch = asyncio.ensure_future(watch_extension(chrome))
    try:
        try:
            await shares.watch()
        except Exception as exc:
            # A failing window watch (a desktop switch) must not take the endpoint watch with it: report it,
            # then keep that watch up until the session itself is torn down (a cancel).
            print(f"Window watch stopped ({type(exc).__name__}); the Chrome watch keeps running", flush=True)
            await asyncio.Event().wait()
    finally:
        watch, chrome.extension_watch = chrome.extension_watch, None
        if watch:
            watch.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await watch


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
                    result["transport"] = self.browser_of(access).transport
                    if why := self.fallback.why(access, self.browser):
                        result["fallback_reason"] = why
                return result
            finally:
                _ACTIVE.reset(token)

    async def leased(self, access, *args, **kwargs):
        if access.grant and access.grant.get("chrome_cancelled"):
            return await function(self, access, *args, **kwargs)
        keep_watching(self)
        browser = await select_extension(self)
        if isinstance(browser, ExtensionTransport) and not browser.socket and not await browser.ensure():
            if self.auto_transport and not known():
                await browser.close()  # the extension was never installed: the pre-extension default
                self.browser = browser = BrowserConnection(self.report)
                browser.report("not_enabled", "Extension absent; remote debugging fallback. "
                               + browser.detail)
            else:
                await await_extension(browser)  # a disconnect or an update is never a reason for Allow
        await self.fallback.retry(access, browser)
        try:
            if (isinstance(browser, ExtensionTransport) and browser.socket and access.grant
                    and access not in self.fallback.grants):
                async with browser.operation(access):
                    return await function(self, access, *args, **kwargs)
            return await function(self, access, *args, **kwargs)
        finally:
            await self.fallback.settle(access)
    return run


def audit(self, access, message, operation):
    info = {"grant": access.session.window_grant_id, "line": message.get("line_id", ""),
            "process": message.get("agent", ""), "operation": operation,
            "input_length": len(message.get("expression", message.get("value", "")) or "")}
    if message.get("action") == "dialog":
        info.update(operation="dialog", accept=message.get("accept"),
                    input_length=len(message.get("prompt_text", "")))
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


def status(chrome, access):
    """The grant's event status; a live attached page proves page events work."""
    entry = chrome.shares.grants.get(access.session.window_grant_id, {})
    state = entry.get("event_state")
    result = state.status() if state else {"event_counter": 0, "events_supported": False,
                                           "subscription_live": False}
    browser = chrome.browser_of(access)
    if any(p.live and p.page_state == "alive" and (not hasattr(browser, "is_attached")
                                                   or browser.is_attached(p.session))
           for p in chrome.pages.get(access, {}).values()):
        result.update(events_supported=True, subscription_live=True)
    return result
