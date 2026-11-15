"""Chrome provider; UIA fallback keeps the existing window contract."""
import asyncio
import contextlib

from websockets.exceptions import ConnectionClosed

from .cdp_actions import act, evaluate
from .cdp_dialogs import dialog_pointer
from .cdp_mapping import frame, map_window, title_matches
from .cdp_page import Page
from .cdp_recovery import HINT, reload, read as read_page
from .cdp_transport import CDPError, INSTRUCTION
from .chrome_operations import audit, chrome_label, operation, preferred


class Chrome:
    def __init__(self, shares, connection=None, bounds=frame, dialogs=dialog_pointer):
        self.shares, self.session, self.bounds = shares, shares.session, bounds
        self.auto_transport = connection is None
        self.browser = connection or preferred(self.report)
        self.pages, self.reasons, self.selected, self.sources = {}, {}, {}, {}
        self.connecting = None
        self.dialogs = dialogs
        self.transport_lock = asyncio.Lock()

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

    def invalidate(self, access):
        for page in self.pages.get(access, {}).values():
            page.stop()
        state = self.shares.grants.get(access.session.window_grant_id, {}).get("event_state")
        if state:
            state.changed()
            self.shares.queue_change(access.session.window_grant_id)

    def revoke(self, access):
        if hasattr(self.browser, "revoke"):
            self.browser.revoke(access)
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
        if any(p.live and p.page_state == "alive" and (not hasattr(self.browser, "is_attached")
                          or self.browser.is_attached(p.session))
               for p in self.pages.get(access, {}).values()):
            result.update(events_supported=True, subscription_live=True)
        return result

    def audit(self, access, message, operation):
        audit(self, access, message, operation)

    def start(self, access, retry=False):
        """Start approval outside the operation queue; reads continue through UIA while it is pending."""
        if (not access.grant or access.grant.get("process", "").lower() != "chrome.exe"
                or access.gate.revoked.is_set()):
            return
        if access.grant.get("chrome_cancelled"):
            return
        if retry:
            self.browser.request_retry()
        if not self.browser.can_attempt():
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
            if self.browser.state != "connected" or not self.browser.socket:
                self.start(access)
                pending = self.connecting and not self.connecting.done()
                self.reasons[access] = ("Awaiting Chrome approval; using UIA meanwhile" if pending
                                        else self.browser.reason())
                return None
            guard()
            prior = self.pages.get(access, {}).get(self.selected.get(access))
            recovery_target = prior.target if prior and prior.page_state != "alive" else None
            (_, targets), window = await map_window(self.browser, access, guard, self.bounds, recovery_target)
            pages = self.pages.setdefault(access, {})
            scope = {target["targetId"] for target in targets}
            for ident in list(pages):
                if ident not in scope or not pages[ident].live:
                    page = pages.pop(ident)
                    page.stop()
                    await page.close()
            selected_target = grant.get("target_id")
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
                matching = [p for p in matching if p.page_state == "alive" and await p.visible()]
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
            if hasattr(self.browser, "resume") and page.page_state == "alive":
                await self.browser.resume(page)
            if not page.initialized and page.page_state == "alive":
                try:
                    await page.initialize()
                except CDPError:
                    if page.page_state == "alive":
                        raise
            self.reasons.pop(access, None)
            return page
        except (CDPError, OSError, KeyError, TypeError) as exc:
            self.reasons[access] = (str(exc) + "; using UIA" if isinstance(exc, CDPError)
                                    else "Chrome mapping unavailable; using UIA")
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
        result = await read_page(self, access, options, message)
        if result is not None:
            page = self.pages[access][self.selected[access]]
            pointer = await asyncio.to_thread(self.dialogs, access.grant)
            page.guard()
            if pointer:
                result["source_reason"] = pointer
        return result

    def metadata(self, access):
        if access.grant and access.grant.get("chrome_cancelled"):
            return {}  # cancellation requires resharing, never the crash-recovery reload path
        page = self.pages.get(access, {}).get(self.selected.get(access))
        if page and page.page_state != "alive":
            return {"source": "uia", "page_state": page.page_state, "recovery_hint": HINT}
        return {}

    @operation
    async def action(self, access, message):
        self.audit(access, message, "screen_eval" if message.get("type") == "window_eval" else
                   "screen_element_action")
        if (message.get("action") not in ("reload", "set_files") and message.get("type") != "window_eval"
                and self.sources.get(access) == "uia" and message.get("element_id") in access.elements):
            return None
        if message.get("action") == "reload" and not self.browser.socket:
            if not access.grant or access.gate.revoked.is_set():
                return {"status": "failed", "source": "cdp", "error": "consent revoked"}
            self.start(access, retry=True)
            pending = self.connecting and not self.connecting.done()
            return {"status": "failed", "source": "cdp", "error": (
                "Awaiting Chrome approval; call reload again after Chrome allows the connection"
                if pending else self.browser.reason())}
        page = await self.page(access)
        if message.get("action") == "set_files" and (not page or self.sources.get(access) != "cdp"):
            return {"status": "failed", "error": "CDP unavailable; use the Open dialog path instead"}
        if message.get("type") == "window_eval" and not page:
            return {"status": "failed", "error": "screen_eval needs a mapped Chrome window",
                    "source": "uia"}
        # An old CDP id can never dispatch through UIA after a provider switch.
        if message.get("action") == "reload":
            if page:
                page.dispatched = False
            try:
                return await reload(self, access, page)
            except CDPError as exc:
                return {"status": "unconfirmed" if page and page.dispatched else "failed",
                        "source": "cdp", "error": str(exc)}
        if page and page.page_state != "alive":
            return {"status": "failed", **self.metadata(access), "error": HINT}
        if not page:
            metadata = self.metadata(access)
            if self.sources.get(access) == "cdp" or metadata:
                return {"status": "failed", **metadata,
                        "error": HINT if metadata else "CDP unavailable; read the window again"}
            return None
        page.dispatched = False
        page.operation_epoch = page.epoch
        try:
            if message.get("type") == "window_eval":
                return await evaluate(page, message["expression"])
            return await act(page, message)
        except CDPError as exc:
            error = str(exc)
            if message.get("action") == "set_files" and (not page.live or "revoked" in error):
                error += "; use the Open dialog path instead"
            return {"status": "unconfirmed" if page.dispatched else "failed",
                    "source": "cdp", "error": error, "revoked_during": not page.live}
        finally:
            page.operation_epoch = None

    @operation
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
