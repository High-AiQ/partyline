"""Cross-line window authorization and lifecycle, with event-driven helper responses."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import WebSocketDisconnect

from partyline.auth_guard import Principal
from partyline.screen_grants import device_grants, resolve_window, window_share_indicators
from partyline.screen_frames import ShareBuffer
from partyline.screen_account_wire import serve_wire
from partyline.screen_snapshot import owner_state
from partyline.screen_window_grants import share_targets
from tests.window_grant_fixtures import WindowGrantFixture


class WindowGrantTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def test_owner_snapshot_queries_are_shared_across_tabs(self):
        first = SimpleNamespace(screen_owner_id=self.owner["id"], send_json=AsyncMock())
        second = SimpleNamespace(screen_owner_id=self.owner["id"], send_json=AsyncMock())
        self.runtime.sockets = {"alpha": [first], "beta": [second]}
        with patch("partyline.screen_snapshot.owner_state", wraps=owner_state) as build:
            await self.hub._device_event(self.device, True)
        build.assert_called_once_with(self.hub, self.owner["id"])
        self.assertEqual("screen_snapshot", first.send_json.await_args.args[0]["type"])
        self.assertEqual("screen_snapshot", second.send_json.await_args.args[0]["type"])

    async def test_account_wire_pushes_snapshot_and_unregisters_on_disconnect(self):
        await self.grant("a")
        socket = Mock()
        socket.screen_owner_id = self.owner["id"]
        socket.accept = AsyncMock()
        socket.send_json = AsyncMock()
        socket.receive_json = AsyncMock(side_effect=[{"type": "hello", "client_id": "tab"},
                                                    WebSocketDisconnect()])
        await serve_wire(self.runtime, socket, "~account", "owner", "build", "1")
        messages = [call.args[0] for call in socket.send_json.await_args_list]
        self.assertEqual(["hello", "screen_snapshot"], [item["type"] for item in messages])
        self.assertEqual("alpha", messages[1]["indicators"][0]["conv_id"])
        self.assertEqual(set(), self.runtime.sockets["~account"])
        self.runtime.sockets["~account"].add(socket)
        await self.hub.window_grants.revoke("g1")
        self.assertEqual([], socket.send_json.await_args.args[0]["indicators"])

    async def test_socket_hello_and_reconnect_push_current_screen_snapshot(self):
        await self.grant("a")
        for _ in range(2):
            socket = Mock()
            socket.screen_owner_id = self.owner["id"]
            socket.accept = AsyncMock()
            socket.send_json = AsyncMock()
            socket.receive_json = AsyncMock(side_effect=[{"type": "hello", "client_id": "tab"},
                                                        WebSocketDisconnect()])
            sent = []
            socket.send_json.side_effect = lambda item, sent=sent: sent.append(item["type"])
            with patch("partyline.docker_workloads.inventory.kick",
                       side_effect=lambda runtime, sent=sent: sent.append("docker refresh")):
                await self.runtime.websocket(socket, "alpha", "owner", "build", "1")
            messages = [call.args[0] for call in socket.send_json.await_args_list]
            # The Docker refresh, and so its resources push, starts only after the handshake.
            self.assertEqual(["hello", "screen_snapshot", "docker refresh"], sent)
            self.assertEqual("g1", messages[1]["devices"][0]["window_grants"][0]["id"])
            self.assertEqual("alpha", messages[1]["indicators"][0]["conv_id"])

    async def test_share_and_control_changes_push_owner_snapshots(self):
        own = SimpleNamespace(screen_owner_id=self.owner["id"], send_json=AsyncMock())
        self.runtime.sockets = {"beta": [own]}
        region = {"x": 0, "y": 0, "width": 10, "height": 10}
        self.device["monitors"] = [region]
        share = await self.hub.start_share("alpha", self.owner["id"], "owner",
                                           self.device["id"], region, "Alpha")
        def snapshots():
            return [call.args[0] for call in own.send_json.await_args_list
                    if call.args[0]["type"] == "screen_snapshot"]
        self.assertEqual([], snapshots()[-1]["indicators"])
        share.status = "active"
        await self.hub._line_event("alpha", self.hub._share_view(share, self.device))
        self.assertEqual("screen", snapshots()[-1]["indicators"][0]["kind"])
        self.hub.control.expect(share, "owner")
        with patch("partyline.screen_control.notice", new_callable=AsyncMock):
            await self.hub.control.from_helper(
                self.device, {"type": "control_granted", "share_id": share.share_id})
            await self.hub.control.revoke(share, "released")
        self.assertGreaterEqual(len(snapshots()), 4)
        with patch("partyline.screen_share_stop.share_stopped", new_callable=AsyncMock):
            await self.hub.stop_share(share.share_id)
        self.assertEqual([], snapshots()[-1]["indicators"])

    async def test_pair_and_offline_removal_push_device_list(self):
        own = SimpleNamespace(screen_owner_id=self.owner["id"], send_json=AsyncMock())
        self.runtime.sockets = {"alpha": [own]}
        code = self.hub.issue_pair_code(self.owner["id"])
        response = await self.client.post("/api/screen/pair/claim", json={
            "code": code, "device_name": "Laptop", "os": "test"})
        self.assertEqual(200, response.status_code)
        ident = response.json()["device_id"]
        self.assertIn(ident, [device["id"] for device in own.send_json.await_args.args[0]["devices"]])
        response = await self.client.delete("/api/screen/devices/" + ident, headers=self.human(self.owner))
        self.assertEqual(200, response.status_code)
        self.assertNotIn(ident, [device["id"] for device in own.send_json.await_args.args[0]["devices"]])

    async def test_walkthrough_deadline_pushes_share_expiry(self):
        own = SimpleNamespace(screen_owner_id=self.owner["id"], send_json=AsyncMock())
        self.runtime.sockets = {"beta": [own]}
        share = ShareBuffer("take", "alpha", self.device["id"], self.owner["id"], "owner", {})
        self.hub.shares["alpha"] = share
        loop = Mock()
        with patch("partyline.walkthrough_takes.asyncio.get_running_loop", return_value=loop):
            self.hub.walkthroughs.create(share)
        callback = loop.call_later.call_args.args[1]
        await callback()
        self.assertNotIn("alpha", self.hub.shares)
        snapshots = [call.args[0] for call in own.send_json.await_args_list
                     if call.args[0]["type"] == "screen_snapshot"]
        self.assertTrue(snapshots)
        self.assertEqual([], snapshots[-1]["indicators"])

    async def test_grant_lifecycle_notifies_only_owner(self):
        own = SimpleNamespace(screen_owner_id=self.owner["id"], send_json=AsyncMock())
        other = SimpleNamespace(screen_owner_id=self.other_user["id"], send_json=AsyncMock())
        self.runtime.sockets = {"alpha": [own], "beta": [other]}
        await self.grant("a")
        def snapshots():
            return [call.args[0] for call in own.send_json.await_args_list
                    if call.args[0]["type"] == "screen_snapshot"]
        self.assertEqual(1, len(snapshots()))
        self.assertEqual("g1", snapshots()[-1]["devices"][0]["window_grants"][0]["id"])
        await self.hub.window_grants.revoke("g1")
        self.assertEqual(2, len(snapshots()))
        self.assertEqual([], snapshots()[-1]["devices"][0]["window_grants"])
        other.send_json.assert_not_awaited()

    async def test_two_windows_one_process_ambiguity_and_snapshot_isolation(self):
        self.assertTrue((await self.grant("a"))["ok"])
        self.assertTrue((await self.grant("a", "Browser", "g2", 20))["ok"])
        response = await self.read("a")
        self.assertEqual(409, response.status_code)
        self.assertIn("g1: Editor", response.text)
        self.assertIn("g2: Browser", response.text)
        self.assertEqual(409, (await self.act("a")).status_code)
        for title, grant in (("Editor", "g1"), ("g2", "g2")):
            response = await self.read("a", title)
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(grant, response.json()["window"])
            self.assertEqual(grant + "-snapshot", response.json()["snapshot_id"])
            self.assertEqual(200, (await self.act("a", title)).status_code)
        self.assertEqual("g2", self.sent[-1]["grant_id"])

    async def test_different_lines_other_process_refused_holder_named(self):
        await self.grant("a")
        await self.grant("b", "Browser", "g2", 20)
        for ident, _own, foreign, holder in (("a", "g1", "g2", "b"), ("b", "g2", "g1", "a")):
            self.assertEqual(200, (await self.read(ident)).status_code)
            self.assertEqual(200, (await self.act(ident)).status_code)
            for call in (self.read, self.act):
                response = await call(ident, foreign)
                self.assertEqual(403, response.status_code)
                self.assertIn("@" + holder, response.text)
        response = await self.read("peer")
        self.assertEqual(403, response.status_code)
        self.assertIn("no window is shared with you", response.text)

    async def test_stopping_one_and_detaching_target_only_end_own_grants(self):
        await self.grant("a")
        await self.grant("a", "Browser", "g2", 20)
        await self.grant("b", "Terminal", "g3", 30)
        await self.hub.window_grants.from_helper(self.device, {"type": "window_revoked", "grant_id": "g1"})
        self.assertEqual("g2", (await self.read("a")).json()["window"])
        self.db.set_attachment_status("a", "detached", "activation-a")
        await self.hub.window_grants.expire()
        self.assertEqual(401, (await self.read("a")).status_code)
        self.assertEqual("g3", (await self.read("b")).json()["window"])
        self.assertEqual(["g3"], [g["id"] for g in device_grants(self.db, self.device["id"])])
        self.assertIn({"type": "revoke_window", "grant_id": "g2"}, self.sent)

    async def test_owner_revoke_and_machine_cannot_set_or_revoke(self):
        await self.grant("a")
        url = "/api/screen/window-grants/g1"
        self.assertEqual(403, (await self.client.delete(url, headers=self.machine("a"))).status_code)
        response = await self.client.delete(url, headers=self.human(self.other_user))
        self.assertEqual(404, response.status_code)
        self.assertEqual(405, (await self.client.put(url, headers=self.machine("a"), json={})).status_code)
        self.assertEqual(200, (await self.client.delete(url, headers=self.human(self.owner))).status_code)
        self.assertEqual(403, (await self.read("a")).status_code)

    async def test_target_groups_are_live_owner_visible_and_revalidated(self):
        groups = share_targets(self.db, self.owner["id"])
        self.assertEqual({"alpha", "beta"}, {g["line_id"] for g in groups})
        self.assertEqual({"a", "peer"}, {p["attachment_id"] for g in groups if g["line_id"] == "alpha"
                                        for p in g["processes"]})
        with patch("partyline.screen_window_grants.visible_conversation_ids", return_value={"beta"}):
            self.assertEqual(["beta"], [g["line_id"] for g in share_targets(self.db, self.owner["id"])])
            self.assertFalse((await self.grant("a"))["ok"])
        self.assertFalse((await self.grant("ended"))["ok"])
        self.assertFalse((await self.grant("a", runtime_owner="obsolete"))["ok"])
        self.assertFalse((await self.grant("a", hwnd=0))["ok"])
        self.assertEqual([], share_targets(self.db, 99999))
        await self.hub.window_grants.from_helper(
            self.device, {"type": "list_share_targets", "request_id": "list"})
        self.assertEqual("share_targets", self.sent[-1]["type"])

    async def test_scope_survives_races_but_not_resume_or_disconnect(self):
        await self.grant("a")
        async def detach_after_dispatch(message):
            await self.receive(message)
            self.db.set_attachment_status("a", "exited", "activation-a")
        self.device["socket"].send_json = detach_after_dispatch
        self.assertEqual(403, (await self.read("a")).status_code)
        self.db.claim_attachment("a", "next-activation")
        self.assertEqual(403, (await self.read("a")).status_code)
        self.device["socket"].send_json = self.receive
        await self.grant("b", "Browser", "g2", 20)
        await self.hub.window_grants.disconnected(self.device["id"])
        self.assertEqual(403, (await self.read("b")).status_code)

    async def test_owner_indicators_and_same_window_replacement(self):
        await self.grant("a")
        await self.grant("b", "Editor", "g2", 10)
        self.assertEqual(403, (await self.read("a")).status_code)
        self.assertEqual(200, (await self.read("b")).status_code)
        indicators = window_share_indicators(self.db, self.owner["id"])
        self.assertEqual([{"conv_id": "beta", "device_name": "Computer", "kind": "window",
                           "label": "reading Editor for @b"}], indicators)
        self.assertEqual([], window_share_indicators(self.db, self.other_user["id"]))
        principal = Principal(kind="user", name="other", user_id=self.other_user["id"])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            resolve_window(self.hub, principal)

    async def test_actions_keep_rate_limits_per_window(self):
        await self.grant("a")
        self.hub.control.clock = lambda: 0
        for _ in range(self.hub.control.limits.per_second):
            self.assertEqual(200, (await self.act("a")).status_code)
        response = await self.act("a")
        self.assertEqual(409, response.status_code)
        self.assertIn("rate limit", response.text)

    async def test_revoke_survives_helper_disconnect(self):
        await self.grant("a")
        self.device["socket"].send_json = AsyncMock(side_effect=RuntimeError("closed"))
        response = await self.client.delete("/api/screen/window-grants/g1", headers=self.human(self.owner))
        self.assertEqual(200, response.status_code)
        self.assertEqual(403, (await self.read("a")).status_code)
