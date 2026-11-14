"""A CDP page session bound to a revocable HWND grant, with a shared UIA/CDP event clock."""
import hashlib
import uuid

from .cdp_recipes import OBSERVER, STATE, normalize
from .cdp_ax import exposed
from .cdp_settle import Quiet
from .cdp_transport import CDPError, DocumentChanged


class Page:
    def __init__(self, browser, access, target, session, changed):
        self.browser, self.access, self.target, self.session = browser, access, target, session
        self.grant, self.generation = access.grant, access.gate.generation
        self.changed = changed
        self.epoch, self.nodes = 0, {}
        self.navigations = 0
        self.identity = uuid.uuid4().hex[:8]
        self.active, self.live, self.dispatched = False, True, False
        self.initialized = False
        self.operation_epoch = None
        self.quiet = Quiet()
        self.browser.listeners.add(self.event)

    def guard(self, document=True):
        if (not self.live or self.access.grant is not self.grant or self.access.gate.revoked.is_set()
                or self.access.gate.generation != self.generation):
            raise CDPError("consent revoked")
        if document and self.operation_epoch is not None and self.operation_epoch != self.epoch:
            raise DocumentChanged("Page document changed during input; read it again before acting")

    async def call(self, method, params=None):
        self.guard()
        if method.startswith("Input."):
            self.dispatched = True
        return await self.browser.call(method, params, self.session, self.guard)

    def event(self, message):
        if not self.live or message.get("sessionId") != self.session:
            return
        method = message["method"]
        if method.startswith(("DOM.", "Accessibility.", "Page.")) or (
                method == "Runtime.bindingCalled"
                and message.get("params", {}).get("name") == "__partylineChange"):
            frame = message.get("params", {}).get("frame", {})
            main_navigation = method == "Page.frameNavigated" and bool(frame) and not frame.get("parentId")
            if main_navigation:
                self.navigations += 1
            if method == "DOM.documentUpdated" or main_navigation:
                self.epoch += 1
                self.nodes.clear()
            self.quiet.changed()
            self.changed()

    async def initialize(self):
        for domain in ("Page", "DOM", "Accessibility", "Runtime"):
            await self.call(domain + ".enable")
        await self.call("Page.setLifecycleEventsEnabled", {"enabled": True})
        await self.call("Runtime.addBinding", {"name": "__partylineChange",
                                              "executionContextName": "partyline"})
        await self.call("Page.addScriptToEvaluateOnNewDocument",
                        {"source": OBSERVER, "worldName": "partyline"})
        frames = await self.call("Page.getFrameTree")
        async def observe(tree):
            context = await self.call("Page.createIsolatedWorld", {
                "frameId": tree["frame"]["id"], "worldName": "partyline"})
            await self.call("Runtime.evaluate", {"expression": OBSERVER,
                                                "contextId": context["executionContextId"]})
            for child in tree.get("childFrames", []):
                await observe(child)
        await observe(frames["frameTree"])
        self.initialized = True

    async def function(self, backend, recipe, arguments=(), release=True):
        resolved = await self.call("DOM.resolveNode", {"backendNodeId": backend, "objectGroup": "partyline"})
        obj = resolved["object"]["objectId"]
        try:
            result = await self.call("Runtime.callFunctionOn", {
                "objectId": obj, "functionDeclaration": recipe,
                "arguments": [{"value": arg} for arg in arguments], "returnByValue": True})
            if result.get("exceptionDetails"):
                raise CDPError("DOM observation or action failed")
            return result.get("result", {}).get("value", {})
        finally:
            # Revocation forbids even cleanup calls; detaching releases the object group.
            if (release and self.live and self.access.grant is self.grant
                    and not self.access.gate.revoked.is_set()):
                await self.call("Runtime.releaseObject", {"objectId": obj})

    async def visible(self):
        result = await self.call("Runtime.evaluate", {
            "expression": "document.visibilityState === 'visible'", "returnByValue": True})
        return result.get("result", {}).get("value") is True

    async def snapshot(self, options=None):
        options = options or {}
        before = self.access.event_status()["event_counter"]
        if ident := options.get("inspect"):
            node = self.nodes.get(ident)
            if not node or not node.get("backendDOMNodeId"):
                return {"error": "stale or virtual CDP element"}
            fresh = await self.call("Accessibility.getPartialAXTree",
                                    {"backendNodeId": node["backendDOMNodeId"], "fetchRelatives": False})
            node = next((n for n in fresh.get("nodes", [])
                         if n.get("backendDOMNodeId") == node["backendDOMNodeId"]), node)
            if node.get("ignored"):
                return {"error": "element is no longer exposed in Chrome accessibility"}
            dom = await self.function(node["backendDOMNodeId"], STATE)
            item = normalize(node, ident, None, dom)
            return {"source": "cdp", "live": {**dom, "enabled": item["enabled"],
                    "disabled_provenance": item["disabled_provenance"]},
                    "ancestors": [], "grant_root_reached": True, **self.access.event_status()}
        cursor = options.get("cursor")
        state = self.access.walks.get(cursor) if cursor else None
        if cursor and (not state or state["counter"] != before or state["epoch"] != self.epoch):
            return {"elements_unavailable": "tree inconsistent: CDP continuation changed; refresh"}
        if state:
            nodes, index, epoch = state["nodes"], state["index"], state["epoch"]
        else:
            self.access.forget()
            self.nodes.clear()
            epoch = self.epoch
            nodes = exposed((await self.call("Accessibility.getFullAXTree"))["nodes"])
            index = 0
        ids = {n["nodeId"]: hashlib.blake2b(
            f'{self.access.session.window_grant_id}:{self.identity}:{self.target}:{epoch}:'
            f'{n.get("backendDOMNodeId", n["nodeId"])}'
            .encode(), digest_size=8).hexdigest() for n in nodes}
        elements = []
        try:
            for node in nodes[index:index + 2000]:
                ident = ids[node["nodeId"]]
                dom = (await self.function(node["backendDOMNodeId"], STATE, release=False)
                       if node.get("backendDOMNodeId") else {})
                item = normalize(node, ident, ids.get(node.get("parentId")), dom)
                elements.append(item)
                self.nodes[ident] = node
        finally:
            if self.live and self.access.grant is self.grant and not self.access.gate.revoked.is_set():
                await self.call("Runtime.releaseObjectGroup", {"objectGroup": "partyline"})
        await self.call("Runtime.evaluate", {"expression": "0", "returnByValue": True})  # renderer fence
        result = {"source": "cdp", "elements": elements, "snapshot_id": uuid.uuid4().hex,
                  "captured_event_counter": before, **self.access.event_status()}
        self.access.keep(result, cursor)
        if index + 2000 < len(nodes):
            token = uuid.uuid4().hex[:12]
            self.access.walks[token] = {"nodes": nodes, "index": index + 2000,
                                        "counter": before, "epoch": epoch}
            result.update(next_cursor=token, truncated=True)
        return result

    def stop(self):
        self.live = False
        self.browser.listeners.discard(self.event)
        self.nodes.clear()

    async def close(self):
        self.stop()
        if self.browser.socket:
            try:
                await self.browser.call("Target.detachFromTarget", {"sessionId": self.session})
            except CDPError:
                pass
