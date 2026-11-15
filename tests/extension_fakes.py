"""An in-memory native-messaging peer, driven through the production framed socket."""
import asyncio
import io
from unittest.mock import AsyncMock

from partyline_helper.extension_transport import ExtensionTransport
from partyline_helper.native_codec import Decoder, frame, packets, read_frame
from tests.cdp_fakes import Fixture


class ExtensionPeer:
    def __init__(self, fixture):
        self.fixture = fixture
        self.reader = asyncio.StreamReader()
        self.decoder = Decoder()
        self.calls, self.raw_calls = [], []
        self.revoked, self.closed = False, False
        self.resumed = {}
        self.attach_count = 0
        self.pid, self.ambiguous = 12, False
        self.refuse = {}  # tab -> the fixed code the extension answers every attach with
        self.stale, self.released = {}, []  # tab -> a grant id from before an update that still holds it
        self.windows = [dict(id=1, left=10, top=20, width=800, height=600, tabs=[
            dict(id=1, title="Lab", active=True, url="https://example.test"),
            dict(id=2, title="Background", active=False, url="https://background.test")])]

    def write(self, raw):
        message = self.decoder.accept(read_frame(io.BytesIO(raw)))
        if message is None or "token" in message:
            return
        self.raw_calls.append(message)
        ident = message.get("id")
        if message["method"] == "Partyline.dispatch":
            message = {"id": ident, **message["params"]}
        self.calls.append(message)
        method, params = message["method"], message.get("params", {})
        result = {}
        if method == "Partyline.release":
            live = set(params["live"])
            self.released.append(params)
            for tab in params["tabs"]:
                if self.stale.get(tab) not in live:
                    self.stale.pop(tab, None)
            result = {"released": 1}
        elif method == "Target.attachToTarget" and int(params["targetId"]) in self.refuse:
            code = self.refuse[int(params["targetId"])]
            self.feed({"id": ident, "error": {"message": "refused", "code": code}})
            return
        elif method == "Target.attachToTarget" and int(params["targetId"]) in self.stale:
            self.feed({"id": ident, "error": {"message": "refused", "code": "tab_owned_by_other_grant"}})
            return
        if method == "Partyline.windows":
            result = {"_partyline_browser_pid": self.pid, "windows": self.windows}
            if self.ambiguous:
                result["windows"] *= 2
        elif method == "Target.attachToTarget":
            self.attach_count += 1
            result = {"sessionId": f'{message["grant"]}:{params["targetId"]}:{self.attach_count}'}
            self.feed({"method": "Partyline.attachment", "sessionId": result["sessionId"],
                       "params": {"attached": True}})
        elif method == "Partyline.resume":
            result, self.resumed = self.resumed, {}
        elif method == "Partyline.revoke":
            self.revoked = True
        elif method.startswith(('Page.', 'DOM.', 'Runtime.', 'Accessibility.', 'Input.')):
            result = self.fixture.socket.response({"method": method, "params": params,
                                                   "sessionId": message.get("sessionId")})
        if ident is not None:
            self.feed({"id": ident, "result": result})

    def feed(self, message):
        for packet in packets(message):
            self.reader.feed_data(frame(packet))

    async def drain(self):
        pass

    def close(self):
        self.closed = True
        self.reader.feed_eof()

    async def wait_closed(self):
        pass


def fixture():
    f = Fixture()
    peer = ExtensionPeer(f)
    browser = ExtensionTransport(discovery=lambda: {"port": 1234, "token": "x" * 64},
                                 opener=AsyncMock(return_value=(peer.reader, peer)))
    f.chrome.browser = f.browser = browser
    browser.changed = f.chrome.report
    return f, peer
