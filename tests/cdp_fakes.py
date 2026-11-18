"""A deterministic websocket peer for the helper's actual CDP multiplexer."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from partyline_helper.cdp import Chrome
from partyline_helper.cdp_recipes import ACTION_STATE, DISPATCH
from partyline_helper.cdp_transport import BrowserConnection
from partyline_helper.status import Status
from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_event_state import EventState
from partyline_helper.window_shares import WindowSession, WindowShares
from tests.cdp_select_fake import NativeSelect


class Socket:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.calls, self.closed, self.hook = [], False, None
        self.windows = {"a": 1, "b": 1, "other": 2}
        self.rects = {1: dict(left=10, top=20, width=800, height=600),
                      2: dict(left=900, top=20, width=800, height=600)}
        self.visible = {"a": True, "b": False, "other": True}
        self.titles = {"a": "Lab", "b": "Background", "other": "Other"}
        self.urls = {}  # target -> url; empty unless a test needs pages to report one
        self.nodes = [dict(nodeId="1", backendDOMNodeId=1, role={"value": "RootWebArea"},
                           name={"value": "Lab"}),
                      dict(nodeId="2", parentId="1", backendDOMNodeId=2, role={"value": "link"},
                           name={"value": "Manage listing content"}),
                      dict(nodeId="3", parentId="1", backendDOMNodeId=3, role={"value": "combobox"},
                           name={"value": "Choice"})]
        self.states = {1: {}, 2: dict(tag="A", aria_disabled=True, hit=True),
                       3: dict(tag="SELECT", value="old", selected_index=0, selected_count=1, hit=True)}
        self.eval_value = {"ok": True}
        self.frame_offsets, self.box_quads = {}, {}
        self.document = {}
        self.options = [dict(label="Old", value="old"), dict(label="New", value="New")]
        self.focused = None
        self.input_events = []
        self.native_select = NativeSelect(self)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.queue.get()
        if value is None:
            raise StopAsyncIteration
        return json.dumps(value)

    def event(self, method="DOM.childNodeInserted", session="a", **params):
        self.queue.put_nowait(dict(method=method, sessionId=session, params=params))

    async def send(self, raw):
        message = json.loads(raw)
        self.calls.append(message)
        if self.hook:
            self.hook(message)
        result = self.response(message)
        self.queue.put_nowait(dict(id=message["id"], result=result))

    def response(self, m):
        method, p = m["method"], m["params"]
        if method == "SystemInfo.getProcessInfo":
            return {"processInfo": [{"type": "browser", "id": 12}]}
        if method == "Target.getTargets":
            return {"targetInfos": [{"targetId": ident, "type": "page", "title": self.titles[ident],
                                     "url": self.urls.get(ident, "")}
                                    for ident in self.windows]}
        if method == "Browser.getWindowForTarget":
            ident = self.windows[p["targetId"]]
            return {"windowId": ident, "bounds": self.rects[ident]}
        if method == "Target.attachToTarget":
            return {"sessionId": p["targetId"]}
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "main"}}}
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 1}
        if method == "Accessibility.getFullAXTree":
            return {"nodes": self.nodes}
        if method == "DOM.getDocument":
            return {"root": self.document}
        if method == "DOM.resolveNode":
            return {"object": {"objectId": str(p["backendNodeId"])}}
        if method == "Runtime.callFunctionOn":
            backend = int(p["objectId"])
            if p["arguments"] or p["functionDeclaration"] == self.native_select.blur:
                return {"result": {"value": self.native_select.function(backend, p)}}
            state = {"connected": backend in self.states, "document_identity": "document",
                     "bounds": [0, 0, 100, 40], **self.states.get(backend, {})}
            if "non_element" in state:  # a text or document node answers only its node type
                return {"result": {"value": {"non_element": state["non_element"]}}}
            if p["functionDeclaration"] == ACTION_STATE:
                state["hidden"] = self.states.get(backend, {}).get("hidden", False)
            if p["functionDeclaration"] == DISPATCH:
                left, top, right, bottom = state["bounds"]
                state.update(x=(left + right) / 2, y=(top + bottom) / 2)
            if state.get("hit") is False:
                state = {**state, "reason": state.get("reason") or "element is covered"}
            return {"result": {"value": state}}
        if method == "DOM.focus":
            self.focused = p["backendNodeId"]
        if method == "Input.dispatchKeyEvent" and p["type"] == "keyDown":
            self.native_select.key(p)
        if method == "Runtime.evaluate":
            value = self.visible.get(m.get("sessionId")) if "visibilityState" in p["expression"] \
                else self.eval_value
            return {"result": {"value": value}}
        if method == "DOM.getBoxModel":
            backend = p["backendNodeId"]
            left, top, right, bottom = self.states.get(backend, {}).get("bounds", [0, 0, 100, 40])
            dx, dy = self.frame_offsets.get(backend, (0, 0))
            quad = [left + dx, top + dy, right + dx, top + dy,
                    right + dx, bottom + dy, left + dx, bottom + dy]
            return {"model": {"content": self.box_quads.get(backend, quad)}}
        return {}

    async def close(self):
        self.closed = True
        self.queue.put_nowait(None)


class Fixture:
    def __init__(self):
        self.socket = Socket()
        self.connector = AsyncMock(return_value=self.socket)
        self.browser = BrowserConnection(discovery=lambda: "ws://fake", connector=self.connector)
        self.session = SimpleNamespace(status=Status(), send=AsyncMock(), tools=SimpleNamespace(audit=Mock()),
                                       share=None, accepted=False)
        self.shares = WindowShares(self.session)
        self.chrome = Chrome(self.shares, self.browser, bounds=lambda hwnd: (10, 20, 800, 600),
                             dialogs=lambda grant: None)
        self.shares.chrome = self.chrome
        self.browser.changed = self.chrome.report
        self.window = dict(hwnd=1, pid=12, title="Lab - Google Chrome", process="chrome.exe")
        session = WindowSession(self.session, "g", lambda: None)
        session.chrome = self.chrome
        self.access = WindowAccess(session, list_windows=lambda: [self.window], platform="win32",
                                   reader=lambda *args, **kw: {"elements": [], "snapshot_id": "uia"})
        session.window = self.access
        self.access.grant = self.window.copy()
        self.access.gate.grant()
        self.state = EventState(clock=lambda: 100)
        self.access.event_status = self.state.status
        self.shares.grants["g"] = dict(access=self.access, event_state=self.state,
                                      title="Lab", target=dict(line_name="line"))

    async def read(self, **options):
        await self.browser.ensure()  # this convenience fixture models an already approved browser
        return await self.chrome.read(self.access, options, dict(agent="agent", line_id="line"))

    async def close(self):
        await self.chrome.close()
        for timer in self.shares.event_timers.values():
            timer.cancel()
        if self.shares.tasks:
            await asyncio.gather(*list(self.shares.tasks), return_exceptions=True)
