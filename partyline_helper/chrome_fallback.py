"""Per-grant fallback from the extension to Chrome's remote debugging.

Chrome refuses extension debugging of some pages (another extension's frame in the page, a tab DevTools
already holds). Only those grants move to remote debugging, with its normal Allow prompt; every other grant
keeps using the extension. Chrome's own error text never reaches here, only the extension's fixed code.
"""
import contextlib

from .cdp_transport import BrowserConnection, ExtensionRefused

SETTINGS = "chrome://inspect/#remote-debugging"
REASONS = {
    "other_extension_frame": ("Chrome won't let extensions debug this page because another extension's frame "
                              f"is in it; enable remote debugging at {SETTINGS} or disable the extension "
                              "that injects it"),
    "debugger_already_attached": ("Chrome won't let the extension debug this page because DevTools or "
                                  "another debugging extension holds it; close that, or enable remote "
                                  f"debugging at {SETTINGS}"),
}


class Fallback:
    def __init__(self, chrome, factory=BrowserConnection):
        self.chrome, self.factory = chrome, factory
        self.remote, self.grants = None, set()

    def of(self, access, default):
        """The connection that serves this grant."""
        return self.remote if access in self.grants and self.remote else default

    def reason(self, error):
        """The actionable explanation for a refusal that has a fallback, else None."""
        return REASONS.get(error.code) if isinstance(error, ExtensionRefused) else None

    async def take(self, access, error):
        """Move this grant to remote debugging when the extension refused it and Chrome allows that."""
        if access in self.grants or not self.reason(error):
            return False
        remote = self.remote or self.factory(self.changed)
        if not remote.discovery():
            return False  # remote debugging is off: the caller reports the actionable reason
        self.remote = remote
        self.grants.add(access)
        print(f"Chrome extension refused {error.method}: {error.code}; this grant uses remote debugging",
              flush=True)
        if hasattr(self.chrome.browser, "revoke"):
            self.chrome.browser.revoke(access)  # the extension drops its hold on this grant's tabs
        self.chrome.invalidate(access)
        for page in self.chrome.pages.pop(access, {}).values():
            await page.close()
        return True

    def changed(self, state, detail=""):
        """Remote debugging's own state: a grant's reason, never the tray's extension row."""
        for access in self.grants:
            if state == "connected":
                self.chrome.reasons.pop(access, None)
            else:
                self.chrome.reasons[access] = detail
                self.chrome.invalidate(access)
            self.chrome.changed(access)

    def drop(self, access):
        self.grants.discard(access)
        if not self.grants and self.remote:
            remote, self.remote = self.remote, None
            self.chrome.shares.spawn(remote.close())

    async def close(self):
        self.grants.clear()
        if self.remote:
            remote, self.remote = self.remote, None
            with contextlib.suppress(OSError):
                await remote.close()
