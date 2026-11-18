"""A CDP page session bound to a revocable HWND grant, with a shared UIA/CDP event clock."""
import hashlib
import uuid

from .cdp_recipes import OBSERVER, STATE, WIDGET_ROLES, normalize, value
from .cdp_ax import exposed
from .cdp_dom_nodes import DETAIL, discover
from .cdp_settle import Quiet
from .cdp_page_dialogs import Dialogs
from .cdp_transport import CDPError, DocumentChanged, ExtensionRefused, PageUnavailable
from .cdp_recovery import Recovery
from .cdp_identity import (CHILD_FRAME, UNRESOLVED, TargetChanged, identity, reprove,
                           token as identity_token, unactionable)


class Page(Dialogs, Recovery):
    def __init__(self, browser, access, target, session, changed):
        self.browser, self.access, self.target, self.session = browser, access, target, session
        self.grant, self.generation = access.grant, access.gate.generation
        self.changed = changed
        self.epoch, self.nodes = 0, {}
        self.parents, self.actionable, self.ax_frames = {}, set(), {}  # this read: links, ids, AX frame ids
        self.main_frame = None
        self.navigations = 0
        self.identity = uuid.uuid4().hex[:8]
        self.active, self.live, self.dispatched = False, True, False
        self.initialized = False
        self.page_state, self.url = "alive", ""
        self.recovery_ready = False
        self.operation_epoch = None
        self.action_proof = None
        self.action_point = None
        self.quiet = Quiet()
        self.browser.listeners.add(self.event)

    def guard(self, document=True, healthy=True):
        if (not self.live or self.grant.get("chrome_cancelled") or self.access.grant is not self.grant
                or self.access.gate.revoked.is_set()
                or self.access.gate.generation != self.generation):
            raise CDPError("consent revoked")
        if healthy and self.page_state != "alive":
            raise PageUnavailable(self.page_state)
        if document and self.operation_epoch is not None and self.operation_epoch != self.epoch:
            raise DocumentChanged(f"Page document changed: page epoch {self.operation_epoch} → {self.epoch}; "
                                  "read it again before acting")

    async def call(self, method, params=None):
        self.dialog_guard()
        if method.startswith("Input.") or method == "DOM.setFileInputFiles":
            if not self.dispatched and self.action_proof is not None:
                self.action_point = await reprove(self, self.action_proof,
                                                 mouse=method == "Input.dispatchMouseEvent")
                self.guard()
            if (method == "Input.dispatchMouseEvent" and self.action_proof is not None
                    and self.action_point is not None):
                params = {**params, **self.action_point}
            self.dispatched = True
        try:
            return await self.browser.call(method, params, self.session, self.dialog_guard)
        except PageUnavailable as exc:
            self.unavailable(exc.state)
            raise

    def event(self, message):
        if not self.live:
            return
        self.health_event(message)
        if message.get("sessionId") != self.session:
            return
        method = message["method"]
        self.dialog_event(method, message.get("params", {}))
        if method.startswith(("DOM.", "Accessibility.", "Page.")) or (
                method == "Runtime.bindingCalled"
                and message.get("params", {}).get("name") == "__partylineChange"):
            frame = message.get("params", {}).get("frame", {})
            main_navigation = method == "Page.frameNavigated" and bool(frame) and not frame.get("parentId")
            if main_navigation:
                self.navigations += 1
                self.url = frame.get("url") or self.url
            if method == "DOM.documentUpdated" or main_navigation:
                self.epoch += 1
                self.nodes.clear()
            self.quiet.changed()
            self.changed()

    async def initialize(self):
        for domain in ("Inspector", "Page", "DOM", "Accessibility", "Runtime"):
            await self.call(domain + ".enable")
        await self.call("Page.setLifecycleEventsEnabled", {"enabled": True})
        await self.call("Runtime.addBinding", {"name": "__partylineChange",
                                              "executionContextName": "partyline"})
        await self.call("Page.addScriptToEvaluateOnNewDocument",
                        {"source": OBSERVER, "worldName": "partyline"})
        frames = await self.call("Page.getFrameTree")
        self.url = frames["frameTree"]["frame"].get("url") or self.url
        self.main_frame = frames["frameTree"]["frame"].get("id")
        async def observe(tree):
            context = await self.call("Page.createIsolatedWorld", {
                "frameId": tree["frame"]["id"], "worldName": "partyline"})
            await self.call("Runtime.evaluate", {"expression": OBSERVER,
                                                "contextId": context["executionContextId"]})
            for child in tree.get("childFrames", []):
                await observe(child)
        await observe(frames["frameTree"])
        self.initialized = True

    async def function(self, backend, recipe, arguments=(), release=True, proof=False):
        try:
            resolved = await self.call("DOM.resolveNode", {
                "backendNodeId": backend, "objectGroup": "partyline"})
        except CDPError as exc:
            if proof and type(exc) is CDPError:
                self.guard()  # revocation or document loss must retain its own refusal
                raise TargetChanged("backend node no longer resolves") from exc
            # A read may keep a node Chrome (or the extension) explicitly refused to resolve; timeouts,
            # socket errors and runtime failures after it resolved are never labelled this way.
            exc.unresolved = getattr(exc, "rejected", False) or (
                isinstance(exc, ExtensionRefused) and exc.code == "debugger_command_failed")
            raise
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
            if (release and self.live and self.page_state == "alive" and self.access.grant is self.grant
                    and not self.access.gate.revoked.is_set() and not self.page_dialog):
                await self.call("Runtime.releaseObject", {"objectId": obj})

    async def visible(self):
        result = await self.call("Runtime.evaluate", {
            "expression": "document.visibilityState === 'visible'", "returnByValue": True})
        return result.get("result", {}).get("value") is True

    async def snapshot(self, options=None):
        self.dialog_guard()
        options = options or {}
        before = self.access.event_status()["event_counter"]
        if ident := options.get("inspect"):
            node = self.nodes.get(ident)
            if not node or not node.get("backendDOMNodeId"):
                return {"error": "stale or virtual CDP element"}
            fresh = {} if node.get("file_input_discovered") else await self.call(
                "Accessibility.getPartialAXTree",
                {"backendNodeId": node["backendDOMNodeId"], "fetchRelatives": False})
            node = {**node, **next((n for n in fresh.get("nodes", [])
                                  if n.get("backendDOMNodeId") == node["backendDOMNodeId"]), {})}
            if node.get("ignored") and not node.get("dom_discovered"):
                return {"error": "element is no longer exposed in Chrome accessibility"}
            dom = await self.function(node["backendDOMNodeId"], STATE)
            if node.get("dom_discovered"):
                dom.update(await self.function(node["backendDOMNodeId"], DETAIL))
                if dom.get("hidden"):
                    return {"error": "element is no longer visible"}
            if node.get("file_input_discovered") and (dom.get("tag"), dom.get("type")) != ("INPUT", "file"):
                return {"error": "element is no longer a file input"}
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
            self.parents.clear()
            self.actionable.clear()
            self.ax_frames.clear()
            epoch = self.epoch
            raw = (await self.call("Accessibility.getFullAXTree"))["nodes"]
            nodes = exposed(raw)
            # Keep upload targets in the first chunk, before a large AX tree reaches the server cap.
            nodes[1:1] = await discover(self, raw)
            index = 0
        ids = {n["nodeId"]: hashlib.blake2b(
            f'{self.access.session.window_grant_id}:{self.identity}:{self.target}:{epoch}:'
            f'{n.get("backendDOMNodeId", n["nodeId"])}'
            .encode(), digest_size=8).hexdigest() for n in nodes}
        elements, parents, actionable = [], self.parents, self.actionable
        try:
            for node in nodes[index:index + 2000]:
                ident = ids[node["nodeId"]]
                dom, unreachable = {}, None
                # A frame id on the node or its nearest ancestor in this read is the only frame evidence.
                above = self.ax_frames.get(ids.get(node.get("parentId")))
                frame = self.ax_frames[ident] = node.get("frameId") or above
                if node.get("backendDOMNodeId"):
                    try:
                        dom = await self.function(node["backendDOMNodeId"], STATE, release=False)
                    except CDPError as exc:
                        if not getattr(exc, "unresolved", False):
                            raise
                        self.guard()  # revocation or document loss keeps its own refusal
                        unreachable = (CHILD_FRAME if frame and self.main_frame and frame != self.main_frame
                                       else UNRESOLVED)
                named = value(node.get("name")) or dom.get("aria_label") or dom.get("title")
                if not unreachable and not node.get("file_input_discovered") and (
                        node.get("dom_discovered") or not named
                        and (dom.get("focusable") or dom.get("role") in WIDGET_ROLES | {"gridcell"})):
                    dom.update(await self.function(node["backendDOMNodeId"], DETAIL, release=False))
                    # AX can expose zero-size controls activated through their visible labels.
                    if node.get("dom_discovered") and dom.get("hidden"):
                        continue
                item = normalize(node, ident, ids.get(node.get("parentId")), dom)
                proof = identity(self, dom)
                item["action_token"] = identity_token(ident, proof)
                parents[ident] = item["parent"]
                extra = {}
                if why := unactionable(node, dom, unreachable):
                    above = item["parent"]
                    for _ in range(64):  # the parent chain is already in this read
                        if above is None or above in actionable:
                            break
                        above = parents.get(above)
                    item.update(actionable=False, why=why)
                    if above in actionable:
                        item["act_on"] = above
                    extra = {"not_actionable": why, "act_on": item.get("act_on")}
                else:
                    actionable.add(ident)
                elements.append(item)
                self.nodes[ident] = {**node, "action_identity": proof, "action_token": item["action_token"],
                                     **extra}
        finally:
            if (self.live and self.page_state == "alive" and self.access.grant is self.grant
                    and not self.access.gate.revoked.is_set() and not self.page_dialog):
                await self.call("Runtime.releaseObjectGroup", {"objectGroup": "partyline"})
        await self.call("Runtime.evaluate", {"expression": "0", "returnByValue": True})  # renderer fence
        result = {"source": "cdp", "action_identity_supported": True,
                  "elements": elements, "snapshot_id": uuid.uuid4().hex,
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
