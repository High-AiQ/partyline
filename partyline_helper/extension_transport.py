"""CDP-compatible transport over the extension's authenticated native port."""
import asyncio
import contextlib
from contextlib import asynccontextmanager

from .cdp_mapping import same_bounds, title_matches
from .cdp_transport import BrowserConnection, CDPError, ExtensionRefused
from .native_host import discover
from .native_socket import NativeSocket

STALE_HOLDS = frozenset({"tab_owned_by_other_grant", "previous_detach_incomplete"})


class ExtensionTransport(BrowserConnection):
    transport = "extension"

    def __init__(self, changed=lambda state, detail: None, discovery=discover,
                 opener=asyncio.open_connection):
        super().__init__(changed, discovery, self.connect)
        self.opener = opener
        self.targets, self.grants, self.attached = {}, {}, set()
        self.tabinfo = {}  # tab id -> (url, title) as last mapped, to find the same tab on another transport
        self.cancelled = set()
        self.listeners.add(self.event)
        self.detail = "Load Partyline Chrome once at chrome://extensions"

    def can_attempt(self):
        return not self.closed and not self.socket and (self.state != "refused" or self.retry_requested)

    def reason(self):
        return self.detail

    def report(self, state, detail=""):
        if state == "awaiting_approval":
            detail = "Connecting to Partyline Chrome"
        elif state in ("refused", "disconnected"):
            detail = "Chrome extension disconnected; click its toolbar button to reconnect"
        super().report(state, detail)

    def denial(self, access):
        if (access.session.window_grant_id in self.cancelled
                or access.grant and access.grant.get("chrome_cancelled")):
            return "Debugging cancelled in Chrome; share this window again to use CDP"
        return None

    def event(self, message):
        if message.get("method") == "Partyline.grantCancelled":
            ident = message["params"]["grant"]
            self.cancelled.add(ident)
            if grant := self.grants.get(ident):
                grant["chrome_cancelled"] = True
        if message.get("method") == "Partyline.attachment":
            session = message.get("sessionId")
            if message.get("params", {}).get("attached"):
                self.attached.add(session)
            else:
                self.attached.discard(session)

    def is_attached(self, session):
        return session in self.attached

    async def connect(self, endpoint, **kwargs):
        try:
            reader, writer = await self.opener("127.0.0.1", endpoint["port"])
            socket = NativeSocket(reader, writer)
            socket.send_nowait({"token": endpoint["token"]})
            return socket
        except (OSError, KeyError, TypeError) as exc:
            raise CDPError("Chrome extension not connected") from exc

    async def call(self, method, params=None, session=None, guard=lambda: None, on_result=None):
        if method == "Target.attachToTarget":
            target = str((params or {}).get("targetId"))
            grant = self.targets.get(target)
            if not grant or not self.grants.get(grant) or grant in self.cancelled:
                raise CDPError("Tab outside live grant")
            try:
                return await self.control(method, params, grant, guard, on_result)
            except ExtensionRefused as exc:
                if exc.code not in STALE_HOLDS or not target.isdigit():
                    raise
                # A hold left by a grant that no longer exists (an update, a lock, a reconnect): release
                # it for this tab only, then try once more. A second refusal is reported with its code.
                await self.release_stale(int(target), guard)
                return await self.control(method, params, grant, guard, on_result)
        return await super().call(method, params, session, guard, on_result)

    async def release_stale(self, tab, guard=lambda: None):
        """Ask the extension to drop this tab's entries under grants this helper no longer has."""
        return await super().call("Partyline.dispatch", {"method": "Partyline.release", "grant": None,
                                  "params": {"tabs": [tab], "live": sorted(self.grants)}}, guard=guard)

    async def control(self, method, params=None, grant=None, guard=lambda: None, on_result=None):
        # Standard CDP params carry the grant only at the native boundary.
        return await super().call("Partyline.dispatch", {"method": method, "params": params or {},
                                  "grant": grant}, guard=guard, on_result=on_result)

    def revoke(self, access):
        ident = access.session.window_grant_id
        self.grants.pop(ident, None)
        self.targets = {t: g for t, g in self.targets.items() if g != ident}
        if self.socket:
            with contextlib.suppress(OSError, RuntimeError):
                self.socket.send_nowait({"method": "Partyline.revoke", "grant": ident})

    @asynccontextmanager
    async def operation(self, access):
        ident = access.session.window_grant_id
        if self.denial(access):
            yield
            return
        self.grants[ident] = access.grant
        if not self.socket:
            await self.ensure()
        if not self.socket:
            raise CDPError("Extension disconnected; read again before acting")
        try:
            await self.control("Partyline.begin", grant=ident)
            yield
        finally:
            if self.socket:
                with contextlib.suppress(CDPError):
                    await self.control("Partyline.end", grant=ident)

    async def map_window(self, access, guard, bounds):
        grant = access.grant
        windows = await asyncio.to_thread(access.list_windows)
        guard()
        native = next((w for w in windows or [] if w["hwnd"] == grant["hwnd"]
                       and w["pid"] == grant["pid"]), None)
        if not native:
            raise CDPError("Chrome window closed or desktop unavailable")
        rect = await asyncio.to_thread(bounds, grant["hwnd"])
        result = await self.call("Partyline.windows", guard=guard)
        if result.get("_partyline_browser_pid") != grant["pid"]:
            raise CDPError("Chrome browser process does not match the shared HWND")
        matches = [w for w in result["windows"] if same_bounds(w, rect)
                   and any(t.get("active") and title_matches(t.get("title", ""), native["title"])
                           for t in w["tabs"])]
        if len(matches) != 1:
            raise CDPError("Chrome window mapping ambiguous or missing")
        window = matches[0]
        active_titles = [t.get("title", "") for t in window["tabs"] if t.get("active")]
        native_matches = set()
        for candidate in windows:
            if (candidate["pid"] == grant["pid"]
                    and any(title_matches(title, candidate["title"]) for title in active_titles)):
                candidate_rect = await asyncio.to_thread(bounds, candidate["hwnd"])
                guard()
                if all(abs(a - b) <= 16 for a, b in zip(candidate_rect, rect, strict=True)):
                    native_matches.add(candidate["hwnd"])
        if native_matches != {grant["hwnd"]}:
            raise CDPError("Chrome native window mapping ambiguous across profiles or incognito")
        if self.denial(access):
            raise CDPError(self.denial(access))
        ident = access.session.window_grant_id
        guard()
        self.grants[ident] = grant
        tabs = [t for t in window["tabs"] if not grant.get("target_id")
                or str(t["id"]) == grant["target_id"]]
        await self.control("Partyline.scope", {"tabs": [t["id"] for t in tabs],
                                               "windowId": window["id"]}, ident, guard)
        self.targets.update({str(t["id"]): ident for t in tabs})
        self.tabinfo.update({str(t["id"]): (t.get("url"), t.get("title")) for t in tabs})
        return ((window["id"], [{"targetId": str(t["id"]), "type": "page", **t} for t in tabs]), native)

    async def resume(self, page):
        result = await self.call("Partyline.resume", {"sessionId": page.session}, guard=page.guard)
        if result.get("reattached"):
            page.initialized = False
            # Child sessions expire with the root debugger attachment.
            for target in list(getattr(page, "frames", {})):
                page.drop_frame(target)
        if result.get("documentChanged"):
            page.epoch += 1
            page.nodes.clear()
        if result.get("reattached") or result.get("documentChanged"):
            page.changed()  # DOM changes while detached may not produce UIA events
