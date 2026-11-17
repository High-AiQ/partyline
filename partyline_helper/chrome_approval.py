"""Which shared Chrome windows wait on Chrome's own Allow prompt, reported so the person is shown it."""
import contextlib

from websockets.exceptions import ConnectionClosed


class Approval:
    def __init__(self, chrome):
        self.chrome = chrome
        self.announced = frozenset()  # grants last reported as waiting

    def waiting(self):
        """Grant ids whose Chrome connection waits for the person's click: the default remote-debugging
        connection for every Chrome grant, or the fallback's own connection for the grants moved to it. The
        extension connecting is never an Allow prompt."""
        chrome = self.chrome
        grants = {}
        for ident, entry in chrome.shares.grants.items():
            grant = getattr(entry["access"], "grant", None)
            if grant and grant.get("process", "").lower() == "chrome.exe":
                grants[entry["access"]] = ident
        remote, found = chrome.fallback.remote, set()
        if remote and remote.state == "awaiting_approval":
            found.update(grants[access] for access in chrome.fallback.grants if access in grants)
        if chrome.browser.transport == "remote_debugging" and chrome.browser.state == "awaiting_approval":
            found.update(ident for access, ident in grants.items() if access not in chrome.fallback.grants)
        return frozenset(found)

    def announce(self):
        self.chrome.shares.spawn(self.publish())

    async def publish(self):
        waiting = self.waiting()
        if waiting != self.announced:  # an empty set after a non-empty one is the clear
            self.announced = waiting
            with contextlib.suppress(ConnectionClosed, OSError):
                await self.chrome.session.send("chrome_approval", grant_ids=sorted(waiting))
