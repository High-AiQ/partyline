"""Line-scoped window grants use real routes and no real-time waits."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime
from partyline.screen_routes import register_screen_routes


class WindowGrantFixture:
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(str(Path(self.tmp.name) / "test.db"))
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        self.store = MediaStore(self.db, Path(self.tmp.name) / "media")
        self.hub = register_screen_routes(app, self.runtime, self.store)
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        self.owner = auth_store.create_user(self.db, "owner@example.test", "owner", "unused")
        self.other_user = auth_store.create_user(self.db, "other@example.test", "other", "unused")
        for line in ("paired", "alpha", "beta", "empty"):
            self.db.create_conversation(line, line.title())
        for ident, line in (("a", "alpha"), ("b", "beta"), ("peer", "alpha"), ("ended", "empty")):
            self.db.add_attachment(ident, line, ident, "raw", ["shell"], "/tmp", "activation-" + ident)
        self.db.set_attachment_status("ended", "detached", "activation-ended")
        code = self.hub.issue_pair_code(self.owner["id"], "alpha")
        device_id, _, _, _ = self.hub.claim_pair_code(code, "Computer", "test")
        self.sent = []
        self.device = {"id": device_id, "owner_id": self.owner["id"], "conv_id": "alpha",
                       "name": "Computer", "monitors": [], "helper_version": "1.2.0", "windows": 2,
                       "window_access_enabled": True, "socket": SimpleNamespace(send_json=self.receive)}
        self.db._exec("INSERT INTO screen_device_window_access(device_id,enabled) VALUES(?,1) "
                      "ON CONFLICT(device_id) DO UPDATE SET enabled=1", (device_id,))
        self.hub.devices[device_id] = self.device

    async def asyncTearDown(self):
        await self.client.aclose()
        self.db.close()
        self.tmp.cleanup()

    async def receive(self, message):
        self.sent.append(message)
        if message["type"] in ("read_window_elements", "window_element_action"):
            grant = message["grant_id"]
            response = {"request_id": message["request_id"], "elements": [{"id": grant + "-element"}],
                        "snapshot_id": grant + "-snapshot", "status": "completed"}
            self.hub.elements.receive({"id": "unrelated"}, response)
            self.hub.elements.receive(self.device, response)

    def machine(self, ident):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, ident)}

    def human(self, user):
        return {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}

    async def offer(self, request_id="targets"):
        await self.hub.window_grants.from_helper(
            self.device, {"type": "list_share_targets", "request_id": request_id})
        return self.sent[-1]

    async def grant_line(self, line, title="Editor", grant_id="g1", hwnd=10, **extra):
        """A helper that shares a window with a line, as the picker does."""
        await self.offer()
        await self.hub.window_grants.from_helper(self.device, {"type": "window_grant", "request_id": "req",
            "grant_id": grant_id, "line_id": line, "targets_request_id": "targets",
            "title": title, "process": "editor.exe", "hwnd": hwnd, **extra})
        return self.sent[-1]

    async def grant(self, ident, title="Editor", grant_id="g1", hwnd=10, **extra):
        """Share with the line `ident` is attached to."""
        return await self.grant_line(self.db.get_attachment(ident)["conv_id"], title, grant_id, hwnd, **extra)

    async def read(self, ident, window=None):
        line = self.db.get_attachment(ident)["conv_id"]
        return await self.client.post(f"/api/conversations/{line}/screen-elements",
            params={"window": window} if window else {}, headers=self.machine(ident))

    async def act(self, ident, window=None):
        body = {"element_id": "g1-element", "action": "invoke", **({"window": window} if window else {})}
        return await self.client.post(
            f"/api/conversations/{self.db.get_attachment(ident)['conv_id']}/screen-control/element-action",
            json=body, headers=self.machine(ident))

