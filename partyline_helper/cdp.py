"""No-extension Chrome provider; UIA fallback keeps the existing window contract."""
import asyncio
import contextlib
import json

from websockets.exceptions import ConnectionClosed

from .cdp_actions import act, evaluate
from .cdp_mapping import frame, map_window, title_matches
from .cdp_page import Page
from .cdp_transport import BrowserConnection, CDPError, INSTRUCTION


class Chrome:
    def __init__(self, shares, connection=None, bounds=frame):
        self.shares, self.session, self.bounds = shares, shares.session, bounds
        self.browser = connection or BrowserConnection(self.report)
        self.pages, self.reasons, self.selected, self.sources = {}, {}, {}, {}
        self.connecting = None

    def report(self, state, detail):
        self.session.status.chrome = f"Chrome: {state.replace('_', ' ')}" + (f" — {detail}" if detail else "")
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
            await self.session.send("chrome_state", state=state, detail=detail)

    def invalidate(self, access):
        for page in self.pages.get(access, {}).values():
            page.stop()
        state = self.shares.grants.get(access.session.window_grant_id, {}).get("event_state")
        if state:
            state.changed()
            self.shares.queue_change(access.session.window_grant_id)

    def revoke(self, access):
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
        entry = self.shares.grants.get(access.session.window_grant_id, {})
        state = entry.get("event_state")
        result = state.status() if state else {"event_counter": 0, "events_supported": False,
                                               "subscription_live": False}
        if any(p.live for p in self.pages.get(access, {}).values()):
            result.update(events_supported=True, subscription_live=True)
        return result

    def audit(self, access, message, operation):
        info = {"grant": access.session.window_grant_id, "line": message.get("line_id", ""),
                "process": message.get("agent", ""), "operation": operation,
                "input_length": len(message.get("expression", message.get("value", "")) or "")}
        self.session.tools.audit.append("action", "window", str(info["process"])[:120], "chrome",
                                        json.dumps(info, separators=(",", ":")))

    def start(self, access):
        """Start approval outside the operation queue; reads continue through UIA while it is pending."""
        if not access.grant or access.grant.get("process", "").lower() != "chrome.exe":
            return
        if self.browser.socket or self.browser.closed or self.browser.state == "refused":
            return
        if self.connecting and not self.connecting.done():
            return
        if not self.browser.discovery():
            self.browser.report("not_enabled", INSTRUCTION)
            return
        self.connecting = self.shares.spawn(self.browser.ensure())

    async def attach(self, access, target, pages, guard):
        def arrived(result, abandoned):
            session = result.get("sessionId")
            if not session:
                return
            try:
                guard()
                if abandoned:
                    raise CDPError("attach abandoned")
            except CDPError:
                self.shares.spawn(self.detach(session))
                return
            # Own the session before waking the waiting command: revoke can now always find it.
            pages[target] = Page(self.browser, access, target, session, lambda: self.changed(access, target))
        await self.browser.call("Target.attachToTarget", {"targetId": target, "flatten": True},
                                guard=guard, on_result=arrived)
        return pages[target]

    async def detach(self, session):
        with contextlib.suppress(CDPError):
            await self.browser.call("Target.detachFromTarget", {"sessionId": session})

    async def page(self, access):
        if not access.grant or access.grant.get("process", "").lower() != "chrome.exe":
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
            if self.browser.state != "connected" or not self.browser.socket:
                self.start(access)
                pending = self.connecting and not self.connecting.done()
                self.reasons[access] = ("Awaiting Chrome approval; using UIA meanwhile" if pending
                                        else self.browser.detail)
                return None
            guard()
            (_, targets), window = await map_window(self.browser, access, guard, self.bounds)
            pages = self.pages.setdefault(access, {})
            scope = {target["targetId"] for target in targets}
            for ident in list(pages):
                if ident not in scope or not pages[ident].live:
                    page = pages.pop(ident)
                    page.stop()
                    await page.close()
            candidates = [t for t in targets if title_matches(t.get("title", ""), window["title"])]
            matching = []
            for target in candidates:
                ident = target["targetId"]
                page = pages.get(ident) or await self.attach(access, ident, pages, guard)
                matching.append(page)
            if len(matching) > 1:
                matching = [p for p in matching if await p.visible()]
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
            if not page.initialized:
                await page.initialize()
            self.reasons.pop(access, None)
            return page
        except (CDPError, OSError, KeyError, TypeError) as exc:
            self.reasons[access] = (str(exc) + "; using UIA" if isinstance(exc, CDPError)
                                    else "Chrome mapping unavailable; using UIA")
            self.invalidate(access)
            return None

    def changed(self, access, target=None):
        if target is not None and self.selected.get(access) != target:
            return
        entry = self.shares.grants.get(access.session.window_grant_id)
        if entry:
            entry["event_state"].changed()
            self.shares.queue_change(access.session.window_grant_id)

    async def read(self, access, options, message):
        self.audit(access, message, "screen_elements")
        page = await self.page(access)
        if not page:
            self.sources[access] = "uia"
            return None
        self.sources[access] = "cdp"
        access.event_status = lambda: self.status(access)
        return await page.snapshot(options)

    async def action(self, access, message):
        self.audit(access, message, "screen_eval" if message.get("type") == "window_eval" else
                   "screen_element_action")
        page = await self.page(access)
        if message.get("type") == "window_eval":
            if not page:
                return {"status": "failed", "error": "screen_eval needs a mapped Chrome window",
                        "source": "uia"}
            return await evaluate(page, message["expression"])
        # An old CDP id can never dispatch through UIA after a provider switch.
        if not page:
            if self.sources.get(access) == "cdp":
                return {"status": "failed", "error": "CDP unavailable; read the window again"}
            return None
        page.dispatched = False
        page.operation_epoch = page.epoch
        try:
            return await act(page, message)
        except CDPError as exc:
            return {"status": "unconfirmed" if page.dispatched else "failed",
                    "source": "cdp", "error": str(exc), "revoked_during": not page.live}
        finally:
            page.operation_epoch = None

    async def tabs(self, access):
        """Provider hook for standing-window enumeration: only call with a locally authorized HWND.

        The caller owns the standing-access toggle/grant. Chrome approval remains independent.
        Includes inactive tabs without activating them; other windows stay out of this grant.
        """
        if not await self.page(access):
            return []
        pages = self.pages.get(access, {})
        page = pages[self.selected[access]]
        (_, targets), _ = await map_window(self.browser, access, page.guard, self.bounds)
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
        await self.browser.close()
