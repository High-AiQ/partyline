"""Renderer health survives session loss; recovery stays inside the original revocable grant."""
from .cdp_transport import CDPError, PageUnavailable

HINT = 'Chrome page unavailable; use screen_element_action(element_id="page", action="reload")'


class Recovery:
    def unavailable(self, state):
        self.page_state = state
        self.recovery_ready = False
        self.initialized = False
        self.epoch += 1
        self.nodes.clear()
        self.access.forget()
        self.quiet.changed()
        self.changed()

    def health_event(self, message):
        method, params = message["method"], message.get("params", {})
        own_session = message.get("sessionId") == self.session
        own_target = params.get("targetId") == self.target
        info = params.get("targetInfo", {})
        if method == "Target.targetInfoChanged" and info.get("targetId") == self.target:
            self.url = info.get("url") or self.url
            if info.get("crashed") or info.get("status") == "crashed":
                self.unavailable("crashed")
            self.changed()
        elif (own_session and method == "Inspector.targetCrashed"
              or own_target and method == "Target.targetCrashed"):
            self.unavailable("crashed")
        elif (own_session and method == "Inspector.detached"
              or method == "Target.detachedFromTarget" and params.get("sessionId") == self.session):
            self.unavailable("detached")
        elif own_session and method == "Inspector.targetReloadedAfterCrash":
            self.recovery_ready = True
            self.initialized = False
            self.changed()

    async def raw(self, method, params=None):
        """Recovery commands still check consent before dispatch and after each response."""
        def guard():
            self.guard(document=False, healthy=False)
        try:
            return await self.browser.call(method, params, self.session, guard)
        except PageUnavailable as exc:
            self.unavailable(exc.state)
            raise

    async def probe(self):
        """One renderer check per requested read; no timed retries or new browser approval."""
        self.guard(document=False, healthy=False)
        if self.page_state == "crashed":
            if not self.recovery_ready:
                return False
            self.recovery_ready = False
        try:
            result = await self.raw("Runtime.evaluate", {"expression": "0", "returnByValue": True})
            if result.get("exceptionDetails"):
                return False
        except CDPError:
            self.guard(document=False, healthy=False)
            return False
        return True


async def reload(chrome, access, page):
    if not page:
        browser = chrome.browser_of(access)
        if browser.state != "connected":
            raise CDPError(browser.reason())
        reason = chrome.reasons.get(access, "").removesuffix("; using UIA")
        raise CDPError("reload needs a mapped Chrome page on the approved browser connection"
                       + (f" ({reason})" if reason else ""))
    page.guard(document=False, healthy=False)
    if page.page_state != "alive" and not page.url:
        raise CDPError("last page URL unavailable; use Chrome's Reload button through UIA")
    original = page
    if page.page_state == "detached":
        page = await reattach(chrome, access, page)
        page.page_state = "detached"
    recovering = page.page_state != "alive"
    page.dispatched = original.dispatched = True
    result = await page.raw("Page.navigate" if recovering else "Page.reload",
                            {"url": page.url} if recovering else {})
    if result.get("errorText"):
        raise CDPError("Chrome could not navigate to the last page URL")
    settle = await page.quiet.wait()
    page.guard(document=False, healthy=False)
    page = await reattach(chrome, access, page)
    await page.initialize()
    return {"status": "completed", "source": "cdp", "page_state": "alive", "settle": settle,
            "settled_event_counter": access.event_status()["event_counter"]}


async def reattach(chrome, access, page):
    page.guard(document=False, healthy=False)
    pages = chrome.pages[access]
    url, target = page.url, page.target
    # Keep the old guard alive until the replacement is owned; revoke must gate late attach replies.
    def guard():
        page.guard(document=False, healthy=False)
    try:
        fresh = await chrome.attach(access, target, pages, guard)
    except BaseException:
        if pages.get(target) is not page:
            page.stop()
            chrome.shares.spawn(chrome.detach(page.session, page.browser))
        raise
    fresh.url = url
    fresh.quiet = page.quiet
    page.stop()
    await chrome.detach(page.session, page.browser)
    fresh.guard(document=False, healthy=False)
    return fresh


async def read(chrome, access, options, message):
    chrome.audit(access, message, "screen_elements")
    page = await chrome.page(access)
    access.event_status = lambda: chrome.status(access)
    if page:
        try:
            if page.page_state == "detached":
                state, url = page.page_state, page.url
                page = await reattach(chrome, access, page)
                if page.page_state == "alive":
                    page.page_state, page.url = state, url
                await page.raw("Inspector.enable")
            if page.page_state != "alive" and await page.probe():
                state = page.page_state
                if state == "crashed":
                    page = await reattach(chrome, access, page)
                page.page_state = "alive"
                try:
                    await page.initialize()
                except CDPError:
                    if page.page_state == "alive":
                        page.unavailable(state)
                        page.recovery_ready = True
                    raise
            if page.page_state == "alive":
                chrome.sources[access] = "cdp"
                return await page.snapshot(options)
        except CDPError:
            page.guard(document=False, healthy=False)
            if page.page_state == "alive":
                raise
    if chrome.sources.get(access) != "uia":
        access.forget()
    chrome.sources[access] = "uia"
    if page:
        chrome.reasons[access] = HINT
    return None
