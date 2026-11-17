"""Chrome provider; UIA fallback keeps the existing window contract."""
import asyncio
import contextlib

from websockets.exceptions import ConnectionClosed

from .cdp_operations import action
from .cdp_dialogs import dialog_pointer, with_dialog_pointer
from .cdp_mapping import frame, map_window, title_matches
from .cdp_page import Page
from .cdp_page_dialogs import PageDialog, visible as dialog_visible
from .cdp_recovery import HINT, read as read_page
from .cdp_transport import CDPError, INSTRUCTION
from .chrome_approval import Approval
from .chrome_fallback import Fallback
from .chrome_operations import audit, chrome_label, operation, preferred, status


class Chrome:
    def __init__(self, shares, connection=None, bounds=frame, dialogs=dialog_pointer):
        self.shares, self.session, self.bounds = shares, shares.session, bounds
        self.auto_transport, self.browser = connection is None, connection or preferred(self.report)
        self.pages, self.reasons, self.selected, self.sources = {}, {}, {}, {}
        self.connecting, self.dialogs, self.transport_lock = None, dialogs, asyncio.Lock()
        self.fallback, self.approval = Fallback(self), Approval(self)

    def report(self, state, detail):
        label = chrome_label(self.browser, state)
        self.session.status.chrome = "Chrome: " + label + (f" — {detail}" if detail else "")
        self.session.status.changed()
        self.shares.spawn(self.publish(state, detail))
        for entry in self.shares.grants.values():
            access = entry["access"]
            grant = getattr(access, "grant", None)
            if grant and grant.get("process", "").lower() == "chrome.exe":
                if state == "connected":
                    self.reasons.pop(access, None)
                else:
                    self.reasons[access] = detail
                self.changed(access)
        if state != "connected":
            for access in list(self.pages):
                self.invalidate(access)

    async def publish(self, state, detail):
        with contextlib.suppress(ConnectionClosed, OSError):
            await self.session.send("chrome_state", state=state, detail=detail,
                                    transport=self.browser.transport)
            await self.approval.publish()  # a state change may start or answer an Allow prompt

    def invalidate(self, access):
        for page in self.pages.get(access, {}).values():
            page.stop()
        state = self.shares.grants.get(access.session.window_grant_id, {}).get("event_state")
        if state:
            state.changed()
            self.shares.queue_change(access.session.window_grant_id)

    def browser_of(self, access):
        return self.fallback.of(access, self.browser)

    def revoke(self, access):
        if hasattr(self.browser, "revoke"):
            self.browser.revoke(access)
        self.fallback.drop(access)
        self.invalidate(access)  # synchronous: no more page commands or event payloads
        for page in self.pages.pop(access, {}).values():
            self.shares.spawn(page.close())
        self.reasons.pop(access, None)
        self.selected.pop(access, None)
        self.sources.pop(access, None)
        chrome_grants = [e for e in self.shares.grants.values() if getattr(e["access"], "grant", None)
                         and e["access"].grant.get("process", "").lower() == "chrome.exe"]
        if not chrome_grants and self.connecting and not self.connecting.done():
            self.connecting.cancel()

    def status(self, access):
        return status(self, access)

    def audit(self, access, message, operation):
        audit(self, access, message, operation)

    def start(self, access, retry=False):
        """Start approval outside the operation queue; reads continue through UIA while it is pending."""
        if (not access.grant or access.grant.get("process", "").lower() != "chrome.exe"
                or access.gate.revoked.is_set()):
            return
        if access.grant.get("chrome_cancelled"):
            return
        browser = self.browser_of(access)
        if retry:
            browser.request_retry()
        if not browser.can_attempt():
            return
        if self.connecting and not self.connecting.done():
            return
        if not browser.discovery():
            browser.report("not_enabled", INSTRUCTION)
            return
        self.connecting = self.shares.spawn(browser.ensure())

    async def attach(self, access, target, pages, guard):
        browser = self.browser_of(access)  # a late reply is cleaned up on the connection that sent it
        def arrived(result, abandoned):
            session = result.get("sessionId")
            if not session:
                return
            try:
                guard()
                if abandoned:
                    raise CDPError("attach abandoned")
            except CDPError:
                self.shares.spawn(self.detach(session, browser))
                return
            # Own the session before waking the waiting command: revoke can now always find it.
            pages[target] = Page(browser, access, target, session, lambda: self.changed(access, target))
        await browser.call("Target.attachToTarget", {"targetId": target, "flatten": True},
                                guard=guard, on_result=arrived)
        return pages[target]

    async def detach(self, session, browser=None):
        with contextlib.suppress(CDPError):
            await (browser or self.browser).call("Target.detachFromTarget", {"sessionId": session})

    @operation
    async def page(self, access):
        if not access.grant or access.grant.get("process", "").lower() != "chrome.exe":
            return None
        if access.grant.get("chrome_cancelled"):
            self.reasons[access] = "Debugging cancelled in Chrome; share this window again; using UIA"
            return None
        if hasattr(self.browser, "denial") and (reason := self.browser.denial(access)):
            self.reasons[access] = reason + "; using UIA"
            return None
        grant, generation = access.grant, access.gate.generation
        def guard():
            if (access.grant is not grant or access.gate.revoked.is_set()
                    or access.gate.generation != generation):
                raise CDPError("consent revoked")
        try:
            reason = await access.check(grant)
            guard()
            if reason:
                raise CDPError(reason)
            browser = self.browser_of(access)
            if browser.state != "connected" or not browser.socket:
                self.start(access)
                pending = self.connecting and not self.connecting.done()
                self.reasons[access] = ("Awaiting Chrome approval; using UIA meanwhile" if pending
                                        else browser.reason())
                return None
            guard()
            prior = self.pages.get(access, {}).get(self.selected.get(access))
            recovery_target = prior.target if prior and prior.page_state != "alive" else None
            (_, targets), window = await map_window(browser, access, guard, self.bounds, recovery_target)
            pages = self.pages.setdefault(access, {})
            scope = {target["targetId"] for target in targets}
            for ident in list(pages):
                if ident not in scope or not pages[ident].live:
                    page = pages.pop(ident)
                    page.stop()
                    await page.close()
            selected_target = self.fallback.selected(access, grant.get("target_id"), targets)
            candidates = ([t for t in targets if t.get("targetId") == selected_target]
                          if selected_target else
                          [t for t in targets if t.get("active", True)
                           and title_matches(t.get("title", ""), window["title"])])
            if not candidates and recovery_target:
                candidates = [t for t in targets if t["targetId"] == recovery_target]
            matching = []
            for target in candidates:
                ident = target["targetId"]
                page = pages.get(ident) or await self.attach(access, ident, pages, guard)
                page.url = target.get("url") or page.url
                matching.append(page)
            if len(matching) > 1:
                matching = [p for p in matching if await dialog_visible(p)]
            if len(matching) != 1:
                raise CDPError("Chrome active tab title/visibility ambiguous; using UIA")
            page = matching[0]  # Windows occlusion can hide even the active tab of a covered HWND.
            for ident in list(pages):
                if ident != page.target:
                    await pages.pop(ident).close()  # inactive tabs cannot invalidate the selected page
            if self.selected.get(access) != page.target:
                access.forget()
                self.selected[access] = page.target
                self.changed(access)
            if hasattr(browser, "resume") and page.page_state == "alive" and not page.page_dialog:
                await browser.resume(page)
            if not page.initialized and page.page_state == "alive" and not page.page_dialog:
                try:
                    await page.initialize()
                except PageDialog:
                    page.guard(document=False, healthy=False)
                except CDPError:
                    if page.page_state == "alive":
                        raise
            self.reasons.pop(access, None)
            return page
        except (CDPError, OSError, KeyError, TypeError) as exc:
            if await self.fallback.take(access, exc):
                return await self.page(access)
            self.reasons[access] = (self.fallback.reason(exc) or str(exc)) + "; using UIA" \
                if isinstance(exc, CDPError) else "Chrome mapping unavailable; using UIA"
            if not any(p.live and p.page_state != "alive" for p in self.pages.get(access, {}).values()):
                self.invalidate(access)
            return None

    def changed(self, access, target=None):
        if target is not None and self.selected.get(access) != target:
            return
        entry = self.shares.grants.get(access.session.window_grant_id)
        if entry:
            entry["event_state"].changed()
            self.shares.queue_change(access.session.window_grant_id)

    @operation
    async def read(self, access, options, message):
        return await with_dialog_pointer(self, access, await read_page(self, access, options, message))

    def metadata(self, access):
        if access.grant and access.grant.get("chrome_cancelled"):
            return {}  # cancellation requires resharing, never the crash-recovery reload path
        page = self.pages.get(access, {}).get(self.selected.get(access))
        if page and page.page_state != "alive":
            return {"source": "uia", "page_state": page.page_state, "recovery_hint": HINT}
        return {}

    @operation
    async def action(self, access, message):
        return await action(self, access, message)

    @operation
    async def tabs(self, access):
        """Standing-window enumeration for a locally authorized HWND; inactive tabs are not activated."""
        if not await self.page(access):
            return []
        pages = self.pages.get(access, {})
        page = pages[self.selected[access]]
        (_, targets), _ = await map_window(self.browser_of(access), access, page.guard, self.bounds)
        return [{"hwnd": access.grant["hwnd"], "title": target.get("title", ""),
                 "url": target.get("url", ""), "target_id": target["targetId"],
                 "active": target["targetId"] == page.target} for target in targets]

    async def close(self):
        self.browser.closed = True  # cancellation during helper teardown must not publish a new refusal
        if self.connecting and not self.connecting.done():
            self.connecting.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.connecting
        for access in list(self.pages):
            self.revoke(access)
        await self.fallback.close()
        await self.browser.close()
