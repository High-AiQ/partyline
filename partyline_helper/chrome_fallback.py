"""Per-grant fallback from the extension to Chrome's remote debugging.

Chrome refuses extension debugging of some pages (another extension's frame in the page, a tab DevTools
already holds). Only those grants move to remote debugging, with its normal Allow prompt; every other grant
keeps using the extension. Chrome's own error text never reaches here, only the extension's fixed code.
"""
import contextlib

from .cdp_transport import BrowserConnection, CDPError, ExtensionRefused, INSTRUCTION

SETTINGS = "chrome://inspect/#remote-debugging"
PICK_AGAIN = "pick a tab again"
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
        self.remote, self.grants, self.picked, self.bound = None, set(), {}, {}
        self.because = {}  # grant -> the extension's refusal code that moved it
        self.trying = set()  # grants whose extension retry is in flight; remote stays open until it settles

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
        self.trying.discard(access)
        self.because[access] = error.code
        if target := (access.grant or {}).get("target_id"):  # a picked tab: remember what it was
            self.picked[access] = getattr(self.chrome.browser, "tabinfo", {}).get(str(target))
        print(f"Chrome extension refused {error.method}: {error.code}; this grant uses remote debugging",
              flush=True)
        if hasattr(self.chrome.browser, "revoke"):
            self.chrome.browser.revoke(access)  # the extension drops its hold on this grant's tabs
        self.chrome.invalidate(access)
        for page in self.chrome.pages.pop(access, {}).values():
            await page.close()
        return True

    def selected(self, access, target_id, targets):
        """A picked tab's id belongs to the extension, so it is bound once to a remote target id.

        The first mapping finds the tab by url and title among the granted window's targets, and only
        when exactly one matches. From then on only that target id is the grant's tab, never whatever tab
        later shows the same content. If it was not found, or has since closed, the grant selects nothing
        (never another tab) until the person picks again."""
        if not target_id or access not in self.grants:
            return target_id
        if access not in self.bound:
            want = self.picked.get(access)
            found = [t["targetId"] for t in targets if want and (t.get("url"), t.get("title")) == want]
            self.bound[access] = found[0] if len(found) == 1 else None
            if self.bound[access] is None:
                raise CDPError(f"The picked tab could not be found over remote debugging; {PICK_AGAIN}")
        if not any(t["targetId"] == self.bound[access] for t in targets):
            self.bound[access] = None  # closed: never re-matched by content
        if self.bound[access] is None:
            raise CDPError(f"The picked tab closed; {PICK_AGAIN}")
        return self.bound[access]

    def changed(self, state, detail=""):
        """Remote debugging's own state: a grant's reason, never the tray's extension row."""
        for access in self.grants:
            if state == "connected":
                self.chrome.reasons.pop(access, None)
            else:
                self.chrome.reasons[access] = detail
                self.chrome.invalidate(access)
            self.chrome.changed(access)

    def why(self, access, browser):
        """A short reason this grant is not on the extension, for read replies; None when it is."""
        if access in self.grants:
            return self.because.get(access)
        return "extension_not_installed" if browser.transport == "remote_debugging" else None

    async def retry(self, access, extension):
        """A refused page navigated or reloaded: try the extension again while remote debugging stays open.

        The remote connection is kept until the extension serves the page, so a repeated refusal moves the
        grant back without Chrome asking Allow again."""
        pages = self.chrome.pages.get(access, {}).values()
        if (access not in self.grants or not getattr(extension, "socket", None)
                or not any(page.navigations for page in pages)):
            return
        self.grants.discard(access)
        self.trying.add(access)
        self.chrome.invalidate(access)
        for page in self.chrome.pages.pop(access, {}).values():
            await page.close()

    async def settle(self, access):
        """After an operation: a grant back on the extension forgets its fallback; idle remote closes."""
        if access in self.trying:
            self.trying.discard(access)
            if access not in self.grants:
                self.forget(access)
        await self.release_idle()

    def forget(self, access):
        self.picked.pop(access, None)
        self.bound.pop(access, None)
        self.because.pop(access, None)

    async def release_idle(self):
        """No grant needs remote debugging: close its connection so Chrome's infobar goes away."""
        if not self.grants and not self.trying and self.remote:
            remote, self.remote = self.remote, None
            with contextlib.suppress(OSError):
                await remote.close()
        browser = self.chrome.browser  # the default when the extension was never installed
        if browser.transport == "remote_debugging" and browser.socket and not any(
                getattr(entry["access"], "grant", None) for entry in self.chrome.shares.grants.values()):
            await browser.disconnect()
            browser.next_attempt = 0  # a release is not a refusal: the next grant may connect at once
            browser.report("not_enabled", INSTRUCTION)

    def drop(self, access):
        self.grants.discard(access)
        self.trying.discard(access)
        self.forget(access)
        if not self.grants and not self.trying and self.remote:
            remote, self.remote = self.remote, None
            self.chrome.shares.spawn(remote.close())
        self.chrome.shares.spawn(self.release_idle())

    async def close(self):
        self.grants.clear()
        self.trying.clear()
        if self.remote:
            remote, self.remote = self.remote, None
            with contextlib.suppress(OSError):
                await remote.close()
