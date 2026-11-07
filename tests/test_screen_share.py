"""Native screen helper integration and bounded frame behavior."""
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.media_routes import media_router
from partyline.runtime import ChatRuntime
from partyline.screen_frames import BufferedFrame, ShareBuffer, frames_since, pick_distinct
from partyline.screen_routes import register_screen_routes
from tests.screen_helper_fakes import FakeDesktop


def png(color="red"):
    data = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(data, "PNG")
    return data.getvalue()


class ScreenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.tmp.name}/test.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        self.store = MediaStore(self.db, Path(self.tmp.name) / "media")
        app = FastAPI()
        install_auth_guard(app, self.db)
        self.hub = register_screen_routes(app, self.runtime, self.store)
        app.include_router(media_router(self.runtime, self.store))
        self.client = TestClient(app)
        self.client.__enter__()
        user = auth_store.create_user(
            self.db, "a@example.com", "alice", auth_tokens.hash_password("password1"))
        self.client.headers["Authorization"] = "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])
        self.executor = ThreadPoolExecutor(max_workers=2)

    def tearDown(self):
        self.executor.shutdown(wait=True)
        self.client.__exit__(None, None, None)
        self.db.close()
        self.tmp.cleanup()

    def pair(self):
        code = self.client.post("/api/screen/pair?conv_id=line").json()["code"]
        response = self.client.post("/api/screen/pair/claim", json={
            "code": code, "device_name": "desk", "os": "test"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post("/api/screen/pair/claim", json={
            "code": code, "device_name": "desk", "os": "test"}).status_code, 400)
        return response.json()

    def sync(self, ws):
        # The response follows all preceding helper messages on this socket.
        ws.send_json({"type": "ping"})
        self.assertEqual(ws.receive_json()["type"], "pong")

    def hello(self, ws):
        ws.send_json({"type": "hello", "protocol": 1, "device_name": "desk", "os": "test",
                      "helper_version": "1", "monitors": FakeDesktop().monitors()})
        self.sync(ws)

    def test_full_flow(self):
        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.hello(ws)
            url = "/api/screen/preview?device_id=" + device["device_id"] + "&monitor_id=1"
            future = self.executor.submit(self.client.post, url)
            command = ws.receive_json()
            self.assertEqual(command["type"], "get_preview")
            self.assertEqual(command["monitor_id"], 1)
            ws.send_json({"type": "preview", "request_id": command["request_id"], "monitor_id": 1,
                          "out_width": 32, "out_height": 24, "mime": "image/png"})
            ws.send_bytes(png())
            self.assertEqual(future.result().status_code, 200)
            region = {"x": -100, "y": 0, "width": 100, "height": 100}
            response = self.client.post("/api/screen/shares?conv_id=line", json={
                "device_id": device["device_id"], "region": region})
            self.assertEqual(response.status_code, 200, response.text)
            command = ws.receive_json()
            self.assertEqual(command["type"], "start_share")
            share_id = command["share_id"]
            ws.send_json({"type": "share_accepted", "share_id": share_id})
            self.sync(ws)
            self.assertEqual(self.hub.shares["line"].status, "active")
            frame = {"type": "frame", "share_id": share_id, "request_id": None, "ts_ms": 1,
                     "region": region, "out_width": 32, "out_height": 24,
                     "pointer": {"x": -50, "y": 50, "visible": True}, "mime": "image/png"}
            ws.send_json(frame)
            ws.send_bytes(png())
            self.sync(ws)
            self.assertTrue(self.hub.shares["line"].frames)
            upload = self.client.post("/api/conversations/line/files", data={"include_screen": "true"})
            self.assertEqual(upload.status_code, 200, upload.text)
            self.assertEqual(len(upload.json()["files"]), 1)
            self.assertIn("/api/media/", upload.json()["message"]["body"])
            messages_before = len(self.db.list_messages("line"))
            future = self.executor.submit(
                self.client.post, "/api/conversations/line/screen-frame?mark_pointer=true")
            command = ws.receive_json()
            self.assertEqual(command["type"], "snap")
            frame["request_id"] = command["request_id"]
            ws.send_json(frame)
            ws.send_bytes(png())
            result = future.result()
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(len(self.db.list_messages("line")), messages_before)
            self.assertIn("'x': -50", result.json()["description"])
            file_id = result.json()["file"]["id"]
            self.assertFalse(result.json()["unchanged"])
            again = self.executor.submit(
                self.client.post, "/api/conversations/line/screen-frame?mark_pointer=true")
            command = ws.receive_json()
            frame["request_id"] = command["request_id"]
            ws.send_json(frame)
            ws.send_bytes(png())
            repeated = again.result()
            self.assertTrue(repeated.json()["unchanged"])
            self.assertEqual(repeated.json()["file"]["id"], file_id)
            saved = self.client.get(f"/api/media/{file_id}/original")
            self.assertEqual(saved.status_code, 200)
            self.assertNotEqual(saved.content, png())
            self.assertEqual(self.client.delete("/api/screen/shares/" + share_id).status_code, 200)
            self.assertEqual(ws.receive_json()["type"], "stop_share")
        self.assertEqual(self.client.delete("/api/screen/devices/" + device["device_id"]).status_code, 200)
        self.assertFalse(self.hub.shares)

    def test_pair_expiry_and_no_share(self):
        with patch("partyline.screen_hub.time.time", return_value=100):
            code = self.client.post("/api/screen/pair?conv_id=line").json()["code"]
        with patch("partyline.screen_hub.time.time", return_value=401):
            self.assertEqual(self.client.post("/api/screen/pair/claim", json={"code": code,
                "device_name": "desk", "os": "test"}).status_code, 400)
        self.assertEqual(self.client.post("/api/conversations/line/screen-frame").status_code, 409)

    def test_buffer_selection(self):
        share = ShareBuffer("s", "line", "d", 1, "a", {})
        for i in range(25):
            share.add(BufferedFrame(bytes([i]), i, {}, 1, 1, None, "image/png"))
        self.assertEqual(len(share.frames), 20)
        self.assertEqual([f.ts_ms for f in pick_distinct(frames_since(share, 20))], [22, 23, 24])
        self.assertEqual(pick_distinct(share.frames, 0), [])
        share.add(BufferedFrame(bytes([23]), 25, {}, 1, 1, None, "image/png"))
        self.assertEqual([f.ts_ms for f in pick_distinct(share.frames)], [22, 24, 25])

    def test_socket_auth_decline_disconnect_and_size_cap(self):
        from unittest.mock import AsyncMock
        from starlette.websockets import WebSocketDisconnect

        browser = AsyncMock()
        self.runtime.sockets["line"] = {browser}
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/screen/helper?token=bad") as invalid:
                invalid.receive_json()
        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper?token=" + device["token"], headers={
                "Authorization": ""}) as ws:
            self.hello(ws)
            region = {"x": -100, "y": 0, "width": 100, "height": 100}
            payload = {"device_id": device["device_id"], "region": region}
            response = self.client.post("/api/screen/shares?conv_id=line", json=payload)
            self.assertEqual(response.status_code, 200)
            command = ws.receive_json()
            ws.send_json({"type": "share_declined", "share_id": command["share_id"],
                          "reason": "prompt pending"})
            self.assertEqual(ws.receive_json()["type"], "stop_share")
            self.sync(ws)
            events = [call.args[0] for call in browser.send_json.await_args_list]
            self.assertTrue(any(event.get("share", {}).get("reason") == "prompt pending"
                                for event in events if isinstance(event.get("share"), dict)))
            response = self.client.post("/api/screen/shares?conv_id=line", json=payload)
            self.assertEqual(response.status_code, 200)
            command = ws.receive_json()
            ws.send_json({"type": "share_accepted", "share_id": command["share_id"]})
            ws.send_json({"type": "frame", "share_id": command["share_id"], "request_id": None,
                          "ts_ms": 1, "region": region, "out_width": 1, "out_height": 1,
                          "pointer": None, "mime": "image/png"})
            ws.send_bytes(b"x" * (4 * 1024 * 1024 + 1))
            self.assertEqual(ws.receive_json()["message"], "frame exceeds 4 MB")
            self.assertEqual(len(self.hub.shares["line"].frames), 0)
        self.assertFalse(self.hub.shares)
        self.assertEqual(self.client.delete("/api/screen/devices/" + device["device_id"]).status_code, 200)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as invalid:
                invalid.receive_json()

    def test_snap_timeout_uses_buffer(self):
        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.hello(ws)
            region = {"x": -100, "y": 0, "width": 100, "height": 100}
            self.client.post("/api/screen/shares?conv_id=line", json={
                "device_id": device["device_id"], "region": region})
            share_id = ws.receive_json()["share_id"]
            ws.send_json({"type": "share_accepted", "share_id": share_id})
            ws.send_json({"type": "frame", "share_id": share_id, "request_id": None, "ts_ms": 1,
                          "region": region, "out_width": 32, "out_height": 24,
                          "pointer": None, "mime": "image/png"})
            ws.send_bytes(png())
            self.sync(ws)
            self.assertTrue(self.hub.shares["line"].frames)
            with patch("partyline.screen_requests._await_frame", side_effect=TimeoutError):
                result = self.client.post("/api/conversations/line/screen-frame")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(ws.receive_json()["type"], "snap")

    def test_helper_snap_error_uses_latest_frame(self):
        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.hello(ws)
            region = {"x": -100, "y": 0, "width": 100, "height": 100}
            self.client.post("/api/screen/shares?conv_id=line", json={
                "device_id": device["device_id"], "region": region})
            share_id = ws.receive_json()["share_id"]
            ws.send_json({"type": "share_accepted", "share_id": share_id})
            ws.send_json({"type": "frame", "share_id": share_id, "request_id": None, "ts_ms": 1,
                          "region": region, "out_width": 32, "out_height": 24,
                          "pointer": None, "mime": "image/png"})
            ws.send_bytes(png())
            self.sync(ws)
            future = self.executor.submit(self.client.post, "/api/conversations/line/screen-frame")
            command = ws.receive_json()
            self.assertEqual(command["type"], "snap")
            ws.send_json({"type": "error", "request_id": command["request_id"],
                          "message": "Snap rate limit: wait for the next frame"})
            result = future.result()
            self.assertEqual(result.status_code, 200, result.text)

    def test_helper_preview_error_reaches_the_caller(self):
        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.hello(ws)
            url = "/api/screen/preview?device_id=" + device["device_id"] + "&monitor_id=1"
            future = self.executor.submit(self.client.post, url)
            command = ws.receive_json()
            ws.send_json({"type": "error", "request_id": command["request_id"],
                          "message": "Preview rate limit"})
            result = future.result()
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json()["detail"], "Preview rate limit")

    def test_mcp_tool_contract_and_dispatch(self):
        from partyline.mcp import tools_core
        from unittest.mock import Mock

        names = {item["name"] for item in tools_core.tool_list({"actions": ["read"]})}
        self.assertIn("screen_frame", names)
        client = Mock()
        with patch.object(tools_core, "_target", return_value=("line", {})):
            tools_core.call(client, "screen_frame", {"mark_pointer": True}, {})
        client.request.assert_called_once_with(
            "POST", "/api/conversations/line/screen-frame?mark_pointer=true")

    def test_live_revoke_and_invalid_region(self):
        from starlette.websockets import WebSocketDisconnect

        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.hello(ws)
            devices = self.client.get("/api/screen/devices?conv_id=line").json()["devices"]
            self.assertTrue(devices[0]["online"])
            bad_region = {"x": -101, "y": 0, "width": 100, "height": 100}
            response = self.client.post("/api/screen/shares?conv_id=line", json={
                "device_id": device["device_id"], "region": bad_region})
            self.assertEqual(response.status_code, 409)
            region = {"x": -100, "y": 0, "width": 100, "height": 100}
            payload = {"device_id": device["device_id"], "region": region}
            url = "/api/screen/shares?conv_id=line"
            self.assertEqual(self.client.post(url, json=payload).status_code, 200)
            ws.receive_json()
            self.assertEqual(self.client.post(url, json=payload).status_code, 409)
            revoke = "/api/screen/devices/" + device["device_id"]
            self.assertEqual(self.client.delete(revoke).status_code, 200)
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
            self.assertFalse(self.hub.shares)
            self.assertEqual(self.client.delete(revoke).status_code, 404)

    def test_pair_code_failures_lock_and_issuance_is_limited(self):
        code = self.client.post("/api/screen/pair?conv_id=line").json()["code"]
        body = {"code": code, "device_name": "", "os": "test"}
        for _ in range(3):
            self.assertEqual(self.client.post("/api/screen/pair/claim", json=body).status_code, 400)
        body["device_name"] = "desk"
        self.assertEqual(self.client.post("/api/screen/pair/claim", json=body).status_code, 429)
        for _ in range(4):
            self.assertEqual(self.client.post("/api/screen/pair?conv_id=line").status_code, 200)
        self.assertEqual(self.client.post("/api/screen/pair?conv_id=line").status_code, 429)

    def test_revoke_pending_connection_before_hello(self):
        from starlette.websockets import WebSocketDisconnect

        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.assertIn(device["device_id"], self.hub.pending_sockets)
            response = self.client.delete("/api/screen/devices/" + device["device_id"])
            self.assertEqual(response.status_code, 200)
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
            self.assertNotIn(device["device_id"], self.hub.devices)

    def test_repeated_frame_is_not_attached_twice(self):
        share = ShareBuffer("s", "line", "d", 1, "alice", {}, status="active")
        share.add(BufferedFrame(png(), 1, {}, 32, 24, None, "image/png"))
        self.hub.shares["line"] = share
        first = self.client.post("/api/conversations/line/files", data={"include_screen": "true"})
        self.assertEqual(len(first.json()["files"]), 1)
        second = self.client.post("/api/conversations/line/files", data={"include_screen": "true"},
                                  files={"file": ("note.txt", b"second", "text/plain")})
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(len(second.json()["files"]), 1)
        self.assertEqual(second.json()["files"][0]["filename"], "note.txt")
        share.add(BufferedFrame(png("blue"), 2, {}, 32, 24, None, "image/png"))
        third = self.client.post("/api/conversations/line/files", data={"include_screen": "true"})
        self.assertEqual(len(third.json()["files"]), 1)

    def test_concurrent_sends_attach_each_frame_once(self):
        share = ShareBuffer("s", "line", "d", 1, "alice", {}, status="active")
        share.add(BufferedFrame(png(), 1, {}, 32, 24, None, "image/png"))
        self.hub.shares["line"] = share
        def send():
            return self.client.post("/api/conversations/line/files", data={"include_screen": "true"},
                                    files={"file": ("note.txt", b"text", "text/plain")})
        futures = [self.executor.submit(send) for _ in range(2)]
        responses = [future.result() for future in futures]
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(sorted(len(response.json()["files"]) for response in responses), [1, 2])

    def test_share_started_during_upload_does_not_bypass_share_lock(self):
        import asyncio
        import threading
        from partyline import media_routes

        started, release = threading.Event(), threading.Event()
        original = media_routes._uploads
        async def delayed(files):
            started.set()
            await asyncio.to_thread(release.wait)
            return await original(files)
        def send():
            return self.client.post("/api/conversations/line/files", data={"include_screen": "true"},
                                    files={"file": ("note.txt", b"text", "text/plain")})
        with patch.object(media_routes, "_uploads", side_effect=delayed):
            future = self.executor.submit(send)
            future.add_done_callback(lambda _: started.set())
            try:
                started.wait()
                if future.done():
                    future.result()
                share = ShareBuffer("s", "line", "d", 1, "alice", {}, status="active")
                share.add(BufferedFrame(png(), 1, {}, 32, 24, None, "image/png"))
                self.hub.shares["line"] = share
            finally:
                release.set()
            response = future.result()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["files"]), 1)
        self.assertFalse(share.attached)

    def test_unattached_latest_frame_is_available_after_a_message(self):
        share = ShareBuffer("s", "line", "d", 1, "alice", {}, status="active")
        share.add(BufferedFrame(png(), 1, {}, 32, 24, None, "image/png"))
        self.hub.shares["line"] = share
        user_id = self.db._exec("SELECT id FROM users WHERE handle='alice'").fetchone()[0]
        share.last_message_ts[f"user:{user_id}"] = 1
        response = self.client.post("/api/conversations/line/files", data={"include_screen": "true"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["files"]), 1)

    def test_revocation_rechecked_after_hello(self):
        from starlette.websockets import WebSocketDisconnect

        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.db._exec("UPDATE screen_devices SET revoked_at=1 WHERE id=?", (device["device_id"],))
            ws.send_json({"type": "hello", "protocol": 1, "device_name": "desk", "os": "test",
                          "helper_version": "1", "monitors": []})
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
            self.assertNotIn(device["device_id"], self.hub.devices)

    def test_revoke_cleans_up_when_one_socket_is_already_disconnected(self):
        from unittest.mock import AsyncMock
        from partyline.screen_connections import revoke

        class Socket:
            pass
        bad, good = Socket(), Socket()
        bad.close = AsyncMock(side_effect=OSError("disconnected"))
        good.close = AsyncMock()
        self.hub.pending_sockets["d"] = {bad, good}
        share = ShareBuffer("s", "line", "d", 1, "alice", {})
        self.hub.shares["line"] = share
        self.client.portal.call(revoke, self.hub, "d")
        bad.close.assert_awaited_once()
        good.close.assert_awaited_once()
        self.assertNotIn("line", self.hub.shares)

    def test_revocation_between_hello_and_registration(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from starlette.websockets import WebSocketDisconnect

        device = self.pair()
        ident = device["device_id"]
        async def revoke_during_replacement(*args, **kwargs):
            self.db._exec("UPDATE screen_devices SET revoked_at=1 WHERE id=?", (ident,))
        old_socket = SimpleNamespace(close=AsyncMock(side_effect=revoke_during_replacement))
        self.hub.devices[ident] = {"socket": old_socket}
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            ws.send_json({"type": "hello", "protocol": 1, "device_name": "desk", "os": "test",
                          "helper_version": "1", "monitors": []})
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
            self.assertIs(self.hub.devices[ident]["socket"], old_socket)
            old_socket.close.assert_awaited_once()

    def test_start_and_stop_notice_reach_each_process_only_once(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        for name in ("one", "two"):
            self.db.add_attachment(name, "line", name, "fake", ["fake"], "/tmp", "owner")
            self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (name,))
            self.runtime.live[name] = SimpleNamespace(att={"runtime_owner": "owner"})
        self.runtime.deliver_pending = AsyncMock(return_value=True)
        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.hello(ws)
            region = {"x": -100, "y": 0, "width": 100, "height": 100}
            payload = {"device_id": device["device_id"], "region": region}
            self.client.post("/api/screen/shares?conv_id=line", json=payload)
            share_id = ws.receive_json()["share_id"]
            ws.send_json({"type": "share_accepted", "share_id": share_id})
            self.sync(ws)
            self.assertEqual(self.runtime.deliver_pending.await_count, 2)
            ws.send_json({"type": "frame", "share_id": share_id, "request_id": None,
                          "ts_ms": 1, "region": region, "out_width": 32, "out_height": 24,
                          "pointer": None, "mime": "image/png"})
            ws.send_bytes(png())
            self.client.delete("/api/screen/shares/" + share_id)
            self.assertEqual(self.runtime.deliver_pending.await_count, 4)
            messages = self.db.message_page("line")[0]
            notices = [m for m in messages if m["sender_type"] == "system"]
            self.assertEqual(len(notices), 2)
            self.assertTrue(all("screen_frame" in m["body"] for m in notices))


    def test_invalid_requests_consume_the_ip_limit(self):
        limits = self.hub.limits
        for _ in range(20):
            result = self.client.post("/api/screen/pair/claim", content="not json",
                                      headers={"Content-Type": "application/json"})
            self.assertEqual(result.status_code, 400)
        result = self.client.post("/api/screen/pair/claim", json={})
        self.assertEqual(result.status_code, 429)
        self.assertEqual(len(limits.global_claims), 20)

class PairLimitTest(unittest.TestCase):
    def test_ip_global_code_and_expiry_limits(self):
        from partyline.screen_pair_limits import (
            CODE_FAILURE_LIMIT, GLOBAL_CLAIM_LIMIT, IP_CLAIM_LIMIT, ISSUE_LIMIT, PairLimits,
        )

        limits = PairLimits()
        with patch("partyline.screen_pair_limits.time.monotonic", return_value=100):
            for _ in range(ISSUE_LIMIT):
                self.assertTrue(limits.issue(1))
            self.assertFalse(limits.issue(1))
            for _ in range(IP_CLAIM_LIMIT):
                self.assertTrue(limits.claim("one", "A"))
            self.assertFalse(limits.claim("one", "A"))
            for i in range(GLOBAL_CLAIM_LIMIT - IP_CLAIM_LIMIT):
                self.assertTrue(limits.claim(f"ip-{i}", "B"))
            self.assertFalse(limits.claim("new", "C"))
            for _ in range(CODE_FAILURE_LIMIT):
                limits.failed("BAD")
        with patch("partyline.screen_pair_limits.time.monotonic", return_value=401):
            self.assertTrue(limits.issue(1))
            self.assertTrue(limits.claim("one", "BAD"))


class HelperProtocolCompatibilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_merged_helper_messages_match_server_contracts(self):
        import asyncio
        from partyline.screen_protocol import GetPreview, HelperFrame, HelperPreview, ShareCommand, ShareEnded
        from partyline_helper.client import Session
        from tests.screen_helper_fakes import FakeDesktop, FakeSocket, FakeTerminal

        socket, desktop = FakeSocket(), FakeDesktop()
        helper = Session(socket, desktop, FakeTerminal(), "desk", clock=lambda: 1)
        preview = GetPreview(request_id="preview", monitor_id=1, long_edge=640)
        await helper.dispatch(preview.model_dump())
        self.assertEqual(HelperPreview.model_validate(socket.sent[0]).monitor_id, 1)
        self.assertIsInstance(socket.sent[1], bytes)
        command = ShareCommand(type="start_share", share_id="s", conv_id="line", line_name="Line",
                               requested_by="alice", region={"x": -100, "y": 0, "width": 100, "height": 100})
        message = command.model_dump()
        helper.validate(message)
        helper.share, helper.accepted, helper.started = message, True, 1
        await helper.frame("snap")
        self.assertEqual(HelperFrame.model_validate(socket.sent[2]).request_id, "snap")
        self.assertIsInstance(socket.sent[3], bytes)
        helper.accepted = False
        gate = asyncio.Event()
        helper.worker = asyncio.create_task(gate.wait())
        await helper.dispatch(message)
        decline = ShareEnded.model_validate(socket.sent[4])
        self.assertEqual(decline.reason, "prompt pending")
        helper.worker.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await helper.worker
