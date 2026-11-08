"""The live helper protocol accepts local consent; machine API tokens cannot impersonate it."""
import unittest

from starlette.websockets import WebSocketDisconnect

from partyline import auth_store
from tests import test_screen_share


class WindowSocketTests(unittest.TestCase):
    setUp = test_screen_share.ScreenTest.setUp
    tearDown = test_screen_share.ScreenTest.tearDown
    pair = test_screen_share.ScreenTest.pair
    hello = test_screen_share.ScreenTest.hello
    sync = test_screen_share.ScreenTest.sync

    def test_target_list_grant_read_action_and_owner_revoke_over_socket(self):
        self.db.create_conversation("elsewhere", "Other line")
        self.db.add_attachment("target", "elsewhere", "builder", "raw", ["sh"], "/tmp", "activation")
        machine = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "target")}
        device = self.pair()
        with self.client.websocket_connect("/api/screen/helper", headers={
                "Authorization": "Bearer " + device["token"]}) as ws:
            self.hello(ws)
            ws.send_json({"type": "list_share_targets", "request_id": "list"})
            groups = ws.receive_json()["lines"]
            self.assertEqual(["elsewhere"], [g["line_id"] for g in groups])
            target = groups[0]["processes"][0]
            ws.send_json({"type": "window_grant", "request_id": "grant", "grant_id": "g",
                          "attachment_id": target["attachment_id"], "targets_request_id": "list",
                          "hwnd": 123, "title": "Editor", "process": "app.exe"})
            self.assertTrue(ws.receive_json()["ok"])
            devices = self.client.get("/api/screen/devices?conv_id=line").json()["devices"]
            self.assertEqual("builder", devices[0]["window_grants"][0]["holder"])
            for path, payload, reply in [
                    ("screen-elements", None, {"elements": [{"id": "element"}], "snapshot_id": "snapshot"}),
                    ("screen-control/element-action", {"element_id": "element", "action": "invoke"},
                     {"status": "completed"})]:
                future = self.executor.submit(self.client.post, f"/api/conversations/elsewhere/{path}",
                                              json=payload, headers=machine)
                command = ws.receive_json()
                self.assertEqual("g", command["grant_id"])
                kind = "window_elements" if payload is None else "window_element_result"
                ws.send_json({"type": kind, "request_id": command["request_id"], **reply})
                response = future.result()
                self.assertEqual(200, response.status_code, response.text)
            response = self.client.delete("/api/screen/window-grants/g")
            self.assertEqual(200, response.status_code)
            self.assertEqual({"type": "revoke_window", "grant_id": "g"}, ws.receive_json())
            self.assertEqual(403, self.client.post("/api/conversations/elsewhere/screen-elements",
                                                  headers=machine).status_code)
        with self.assertRaises(WebSocketDisconnect) as error, self.client.websocket_connect(
                "/api/screen/helper", headers=machine) as socket:
            socket.receive_json()
        self.assertEqual(4401, error.exception.code)
