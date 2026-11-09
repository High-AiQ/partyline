"""Native screen helper integration and bounded frame behavior."""
import asyncio
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

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

    def test_account_computer_is_available_for_local_tools_on_accessible_lines(self):
        self.db.create_conversation("other", "Other")
        device = self.pair()
        result = self.db._exec("SELECT * FROM screen_devices WHERE id=?", (device["device_id"],)).fetchone()
        row = dict(result)
        row.update(socket=SimpleNamespace(send_json=AsyncMock()), tools=1)
        self.hub.devices[row["id"]] = row
        for line in ("line", "other"):
            result = asyncio.run(self.hub.tools.request(line, "worker", line.title(), "blender"))
            self.assertEqual(result["status"], "pending")
            self.assertEqual(self.hub.tools.sessions[line].device_id, row["id"])
            command = row["socket"].send_json.await_args.args[0]
            self.assertEqual((command["line_name"], command["requested_by"]), (line.title(), "worker"))
        with patch("partyline.screen_device_access.allows", return_value=False):
            with self.assertRaisesRegex(ValueError, "no paired computer of this line's people is online"):
                self.hub.tools.device("other")
        second = {**row, "id": "second", "name": "laptop"}
        self.hub.devices["second"] = second
        with self.assertRaisesRegex(ValueError, "several computers are online"):
            self.hub.tools.device("line")
        self.assertEqual(self.hub.tools.device("line", "laptop")["id"], "second")

    def test_new_account_device_can_read_window_from_another_line(self):
        self.db.create_conversation("other", "Other")
        self.db.add_attachment("reader", "other", "reader", "raw", ["shell"], "/tmp", "private-activation")
        machine = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "reader")}
        device = self.pair()
        headers = {"Authorization": "Bearer " + device["token"]}
        with self.client.websocket_connect("/api/screen/helper", headers=headers) as ws:
            self.hello(ws)
            self.assertEqual(403, self.client.post(
                "/api/conversations/other/screen-elements", headers=machine).status_code)
            ws.send_json({"type": "list_share_targets", "request_id": "targets"})
            self.assertEqual("reader", ws.receive_json()["lines"][0]["processes"][0]["attachment_id"])
            ws.send_json({"type": "window_grant", "request_id": "grant", "targets_request_id": "targets",
                          "grant_id": "window", "attachment_id": "reader", "hwnd": 10,
                          "title": "Editor", "process": "app.exe"})
            self.assertTrue(ws.receive_json()["ok"])
            future = self.executor.submit(self.client.post, "/api/conversations/other/screen-elements",
                                          headers=machine)
            command = ws.receive_json()
            self.assertEqual(command["type"], "read_window_elements")
            self.assertEqual("window", command["grant_id"])
            ws.send_json({"type": "window_elements", "request_id": command["request_id"],
                          "snapshot_id": "s", "window_title": "Editor",
                          "elements": [{"id": "h", "name": "Hello"}]})
            response = future.result()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["window_title"], "Editor")
            self.assertIn("Hello", response.json()["outline"][0])

    def test_device_change_reaches_only_the_owners_sockets_across_lines(self):
        own = SimpleNamespace(screen_owner_id=1, send_json=AsyncMock())
        other = SimpleNamespace(screen_owner_id=2, send_json=AsyncMock())
        self.runtime.sockets = {"line": [own], "other": [other]}
        asyncio.run(self.hub._device_event({"id": "pc", "owner_id": 1}, True))
        own.send_json.assert_awaited_once_with({"type": "screen_devices_changed", "device_id": "pc",
                                               "online": True})
        other.send_json.assert_not_awaited()

    def test_account_pairing_shares_to_each_line_and_limits_indicators_to_owner(self):
        from partyline.auth_guard import Principal

        self.db.create_conversation("other", "Other")
        device = self.pair()
        ident = device["device_id"]
        row = self.db._exec("SELECT conv_id FROM screen_devices WHERE id=?", (ident,)).fetchone()
        self.assertIsNone(row[0])
        headers = {"Authorization": "Bearer " + device["token"]}
        with self.client.websocket_connect("/api/screen/helper", headers=headers) as ws:
            self.hello(ws)
            self.assertEqual(len(self.client.get("/api/screen/devices?conv_id=other").json()["devices"]), 1)
            for line in ("line", "other"):
                self.assertEqual(self.client.get("/api/screen/active-indicators").json()["indicators"], [])
                response = self.client.post("/api/screen/shares?conv_id=" + line, json={
                    "device_id": ident, "region": {"x": -100, "y": 0, "width": 100, "height": 100}})
                self.assertEqual(response.status_code, 200, response.text)
                command = ws.receive_json()
                self.assertEqual(command["conv_id"], line)
                share_id = command["share_id"]
                ws.send_json({"type": "share_accepted", "share_id": share_id})
                self.sync(ws)
                frame = {"type": "frame", "share_id": share_id, "request_id": None, "ts_ms": 1,
                         "region": {"x": -100, "y": 0, "width": 100, "height": 100},
                         "out_width": 32, "out_height": 24, "mime": "image/png"}
                ws.send_json(frame)
                ws.send_bytes(png())
                self.sync(ws)
                self.assertEqual(list(self.hub.shares), [line])
                self.assertTrue(self.hub.shares[line].frames)
                unrelated = "other" if line == "line" else "line"
                self.assertIsNone(self.client.get("/api/screen/shares?conv_id=" + unrelated).json()["share"])
                self.assertEqual(self.client.post(
                    f"/api/conversations/{unrelated}/screen-frame").status_code, 409)
                items = self.client.get("/api/screen/active-indicators").json()["indicators"]
                self.assertEqual(items, [{"conv_id": line, "device_name": "desk", "kind": "screen",
                                          "label": "desk screen share"}])
                other = Principal(kind="user", name="bob", user_id=999)
                with patch("partyline.screen_routes.request_principal", return_value=other):
                    indicators = self.client.get("/api/screen/active-indicators").json()["indicators"]
                    self.assertEqual(indicators, [])
                    self.assertEqual(self.client.get("/api/screen/devices").json()["devices"], [])
                    self.assertEqual(self.client.post("/api/screen/shares?conv_id=other", json={
                        "device_id": ident, "region": frame["region"]}).status_code, 403)
                machine = Principal(kind="machine", name="bot")
                with patch("partyline.screen_routes.request_principal", return_value=machine):
                    self.assertEqual(self.client.get("/api/screen/active-indicators").status_code, 403)
                self.client.delete("/api/screen/shares/" + share_id)
                self.assertEqual(ws.receive_json()["type"], "stop_share")

    def test_pairing_survives_line_removal_and_database_reopen(self):
        device = self.pair()
        ident = device["device_id"]
        self.db._exec("UPDATE screen_devices SET conv_id='line' WHERE id=?", (ident,))
        self.db._exec("""CREATE TABLE screen_devices_legacy(
            id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, name TEXT NOT NULL,
            os TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, revoked_at REAL)""")
        self.db._exec("INSERT INTO screen_devices_legacy SELECT * FROM screen_devices")
        self.db._exec("DROP TABLE screen_devices")
        self.db._exec("ALTER TABLE screen_devices_legacy RENAME TO screen_devices")
        reopened = Db(self.db.path)
        try:
            reopened._exec("PRAGMA foreign_keys=ON")
            reopened._exec("DELETE FROM conversations WHERE id='line'")
            row = reopened._exec("SELECT id FROM screen_devices WHERE id=?", (ident,)).fetchone()
            self.assertIsNotNone(row)
        finally:
            reopened.close()
        reopened = Db(self.db.path)
        try:
            row = reopened._exec("SELECT id FROM screen_devices WHERE id=?", (ident,)).fetchone()
            self.assertIsNotNone(row)
        finally:
            reopened.close()

    def test_full_flow(self):
        device = self.pair()
        # A legacy row paired on another line can share on this one.
        self.db.create_conversation("legacy", "Legacy")
        self.db._exec("UPDATE screen_devices SET conv_id='legacy' WHERE id=?", (device["device_id"],))
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
            # A resting visible cursor during scrolling keeps its real marker and coordinates.
            frame["pointer"] = {"x": -75, "y": 25, "visible": True}
            for color in ("blue", "green"):
                frame["request_id"] = None
                ws.send_json(frame)
                ws.send_bytes(png(color))
                self.sync(ws)
            for hidden in (False, True):
                if hidden:
                    frame["pointer"] = {"x": -500, "y": 50, "visible": False, "captured": True}
                snap = self.executor.submit(
                    self.client.post, "/api/conversations/line/screen-frame?mark_pointer=true")
                frame["request_id"] = ws.receive_json()["request_id"]
                ws.send_json(frame)
                ws.send_bytes(png())
                captured = snap.result()
                self.assertEqual(captured.status_code, 200, captured.text)
                description = captured.json()["description"]
                if hidden:
                    self.assertIn("view centre; pointer captured", description)
                    self.assertIn("'os': None", description)
                else:
                    self.assertIn("pointer stationary", description)
                    self.assertIn("'os': {'x': -75, 'y': 25}", description)
                    self.assertNotIn("view centre", description)
                content = self.client.get(captured.json()["file"]["urls"]["original"]).content
                with Image.open(io.BytesIO(content)) as image:
                    self.assertEqual(image.getpixel((16, 12) if hidden else (8, 6)), (255, 255, 255))
                    if not hidden:
                        self.assertEqual(image.getpixel((16, 12)), (255, 0, 0))
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
        self.assertIn("screen_elements", names)
        client = Mock()
        with patch.object(tools_core, "_target", return_value=("line", {})):
            tools_core.call(client, "screen_frame", {"mark_pointer": True}, {})
        client.request.assert_called_once_with(
            "POST", "/api/conversations/line/screen-frame?mark_pointer=true")
        client.request.reset_mock()
        with patch.object(tools_core, "_target", return_value=("line", {})):
            tools_core.call(client, "screen_elements", {"device": "My PC"}, {})
        client.request.assert_called_once_with(
            "POST", "/api/conversations/line/screen-elements?device=My%20PC", timeout=60)

    def test_devices_report_the_helper_version_and_flag_an_outdated_helper(self):
        from partyline import __version__

        device = self.pair()
        url = "/api/screen/devices?conv_id=line"
        offline = self.client.get(url).json()["devices"][0]
        self.assertEqual((offline["helper_version"], offline["update_available"]), (None, False))
        headers = {"Authorization": "Bearer " + device["token"]}
        for reported, outdated in (("1", True), (__version__, False), ("unknown", False),
                                   ("9" * 5000, False)):
            with self.client.websocket_connect("/api/screen/helper", headers=headers) as ws:
                ws.send_json({"type": "hello", "protocol": 1, "device_name": "desk", "os": "Windows",
                              "helper_version": reported, "monitors": FakeDesktop().monitors()})
                self.sync(ws)
                online = self.client.get(url).json()["devices"][0]
            self.assertEqual((online["helper_version"], online["update_available"]), (reported, outdated))

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
