"""Line-level window authorization and lifecycle, with event-driven helper responses."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import WebSocketDisconnect

from partyline.auth_guard import Principal
from partyline.screen_grants import device_grants, resolve_window
from partyline.screen_frames import ShareBuffer
from partyline.screen_account_wire import serve_wire
from partyline.screen_snapshot import owner_state, owner_indicators
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
        self.assertEqual(["standing"], [i["kind"] for i in socket.send_json.await_args.args[0]["indicators"]])

    async def test_a_greeting_to_a_socket_closed_underneath_it_is_a_disconnect(self):
        """Every restart logged an ASGI traceback: the hello raced the shutdown's close."""
        from starlette.websockets import WebSocketState

        closed = RuntimeError('Cannot call "send" once a close message has been sent.')
        for line, state, raises in (("~account", WebSocketState.DISCONNECTED, False),
                                    ("alpha", WebSocketState.DISCONNECTED, False),
                                    ("alpha", WebSocketState.CONNECTED, True)):
            socket = Mock(screen_owner_id=self.owner["id"], application_state=state)
            socket.accept = AsyncMock()
            socket.receive_json = AsyncMock(return_value={"type": "hello", "client_id": "tab"})
            socket.send_json = AsyncMock(side_effect=closed)
            with self.subTest(line=line, state=state):
                if raises:  # a send that fails on an open socket is still a fault
                    with self.assertRaises(RuntimeError):
                        await serve_wire(self.runtime, socket, line, "owner", "build", "1")
                else:
                    await serve_wire(self.runtime, socket, line, "owner", "build", "1")
                self.assertNotIn(socket, self.runtime.sockets.get(line, set()))

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
        self.assertEqual(["standing"], [i["kind"] for i in snapshots()[-1]["indicators"]])
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
        self.assertEqual(["standing"], [i["kind"] for i in snapshots()[-1]["indicators"]])

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
        self.assertEqual(["standing"], [i["kind"] for i in snapshots[-1]["indicators"]])

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
        for ident, foreign, holder in (("a", "g2", "Beta"), ("b", "g1", "Alpha")):
            self.assertEqual(200, (await self.read(ident)).status_code)
            self.assertEqual(200, (await self.act(ident)).status_code)
            for call in (self.read, self.act):
                response = await call(ident, foreign)
                self.assertEqual(403, response.status_code)
                self.assertIn("no window is shared with this line", response.text)
                self.assertNotIn(holder, response.text)  # an unrelated line is never named
        self.db.create_conversation("quiet", "Quiet")
        self.db.add_attachment("q", "quiet", "q", "raw", ["shell"], "/tmp", "activation-q")
        response = await self.read("q")
        self.assertEqual(403, response.status_code)
        self.assertIn("no window is shared with this line", response.text)
        self.assertNotIn("Alpha", response.text)

    async def test_every_process_on_a_plain_line_shares_the_grant_before_and_after_attaching(self):
        """Person-attached processes, no captain, no task: the primary case."""
        self.assertTrue((await self.grant("a"))["ok"])
        self.assertEqual(200, (await self.read("peer")).status_code)
        self.db.add_attachment("late", "alpha", "late", "raw", ["shell"], "/tmp", "activation-late")
        for ident in ("a", "peer", "late"):
            self.assertEqual("g1", (await self.read(ident)).json()["window"])
            self.assertEqual(200, (await self.act(ident)).status_code)
        self.assertFalse(any(self.db.get_attachment(i)["is_lead"] for i in ("a", "peer", "late")))
        self.assertIsNone(self.db.get_conversation("alpha")["parent_id"])

    async def test_grant_survives_detach_reattach_and_rotation_replacement(self):
        await self.grant("a")
        self.db.set_attachment_status("a", "detached", "activation-a")
        self.assertEqual(200, (await self.read("peer")).status_code)
        self.db.claim_attachment("a", "next-activation")
        self.db.set_attachment_status("peer", "exited", "activation-peer")
        self.db.add_attachment("successor", "alpha", "successor", "raw", ["shell"], "/tmp", "act-s")
        self.assertEqual(200, (await self.read("successor")).status_code)
        self.assertEqual(["g1"], [g["id"] for g in device_grants(self.db, self.device["id"])])
        self.assertNotIn({"type": "revoke_window", "grant_id": "g1"}, self.sent)

    async def test_archiving_the_line_ends_the_grant(self):
        from partyline.line_subtree import archive_line

        await self.grant("a")
        await self.grant("b", "Browser", "g2", 20)
        with patch("partyline.line_subtree.close_for_line", new_callable=AsyncMock), \
                patch("partyline.line_subtree.docker_relay.stop", new_callable=AsyncMock):
            await archive_line(self.runtime, "alpha")
        self.assertEqual(["g2"], [g["id"] for g in device_grants(self.db, self.device["id"])])
        self.assertIn({"type": "revoke_window", "grant_id": "g1"}, self.sent)
        self.assertNotIn("g1", self.hub.window_grants.known)
        self.assertEqual(403, (await self.read("a")).status_code)

    async def test_stopping_one_window_leaves_the_others_and_the_line_attached(self):
        await self.grant("a")
        await self.grant("a", "Browser", "g2", 20)
        await self.grant("b", "Terminal", "g3", 30)
        await self.hub.window_grants.from_helper(self.device, {"type": "window_revoked", "grant_id": "g1"})
        self.assertEqual("g2", (await self.read("a")).json()["window"])
        self.assertEqual("g2", (await self.read("peer")).json()["window"])
        self.assertEqual("g3", (await self.read("b")).json()["window"])
        await self.hub.window_grants.disconnected(self.device["id"])
        self.assertEqual([], device_grants(self.db, self.device["id"]))

    async def test_owner_revoke_and_machine_cannot_set_or_revoke(self):
        await self.grant("a")
        url = "/api/screen/window-grants/g1"
        self.assertEqual(403, (await self.client.delete(url, headers=self.machine("a"))).status_code)
        response = await self.client.delete(url, headers=self.human(self.other_user))
        self.assertEqual(404, response.status_code)
        self.assertEqual(405, (await self.client.put(url, headers=self.machine("a"), json={})).status_code)
        self.assertEqual(200, (await self.client.delete(url, headers=self.human(self.owner))).status_code)
        self.assertEqual(403, (await self.read("a")).status_code)

    async def test_target_groups_list_every_visible_line_even_without_a_process(self):
        groups = share_targets(self.db, self.owner["id"])
        self.assertEqual({"paired", "alpha", "beta", "empty"}, {g["line_id"] for g in groups})
        self.assertEqual({"a", "peer"}, {p["attachment_id"] for g in groups if g["line_id"] == "alpha"
                                        for p in g["processes"]})
        self.assertEqual([], next(g for g in groups if g["line_id"] == "empty")["processes"])
        old = share_targets(self.db, self.owner["id"], window_lines=False)
        self.assertEqual({"alpha", "beta"}, {g["line_id"] for g in old})
        with patch("partyline.screen_window_grants.visible_conversation_ids", return_value={"beta"}):
            self.assertEqual(["beta"], [g["line_id"] for g in share_targets(self.db, self.owner["id"])])
            self.assertFalse((await self.grant("a"))["ok"])
        self.assertTrue((await self.grant_line("empty"))["ok"])  # share first, attach later
        self.assertFalse((await self.grant_line("missing", grant_id="g2", hwnd=11))["ok"])
        self.assertFalse((await self.grant("a", hwnd=0))["ok"])
        self.assertEqual([], share_targets(self.db, 99999))
        self.assertEqual("share_targets", (await self.offer("list"))["type"])
        self.assertIn("lines", self.sent[-1])
        self.assertIn("empty", [g["line_id"] for g in self.sent[-1]["lines"]])
        self.db.create_conversation("late", "Late")
        self.db.add_attachment("later", "late", "later", "raw", ["shell"], "/tmp", "activation-later")
        self.db.archive_conversation("late")
        self.assertNotIn("late", [g["line_id"] for g in share_targets(self.db, self.owner["id"])])

    async def test_a_grant_to_a_line_with_no_process_serves_the_process_that_attaches_later(self):
        await self.grant_line("empty")
        self.db.add_attachment("fresh", "empty", "fresh", "raw", ["shell"], "/tmp", "activation-fresh")
        self.assertEqual("g1", (await self.read("fresh")).json()["window"])

    async def test_scope_survives_races_and_resume_but_not_disconnect(self):
        await self.grant("a")
        async def detach_after_dispatch(message):
            await self.receive(message)
            self.db.set_attachment_status("a", "exited", "activation-a")
        self.device["socket"].send_json = detach_after_dispatch
        self.assertEqual(200, (await self.read("a")).status_code)
        self.db.claim_attachment("a", "next-activation")
        self.assertEqual(200, (await self.read("a")).status_code)
        self.device["socket"].send_json = self.receive
        await self.grant("b", "Browser", "g2", 20)
        await self.hub.window_grants.disconnected(self.device["id"])
        self.assertEqual(403, (await self.read("b")).status_code)
        self.assertEqual(403, (await self.read("a")).status_code)

    async def test_owner_indicators_and_same_window_replacement(self):
        await self.grant("a")
        await self.grant("b", "Editor", "g2", 10)
        self.assertEqual(403, (await self.read("a")).status_code)
        self.assertEqual(200, (await self.read("b")).status_code)
        self.assertNotIn("g1", self.hub.window_grants.known)
        indicators = [item for item in owner_indicators(self.hub, self.owner["id"])
                      if item["kind"] == "window"]
        self.assertEqual([{"conv_id": "beta", "device_name": "Computer", "kind": "window",
                           "label": "window → «Beta» (and its sublines): Editor"}], indicators)
        self.assertEqual([], owner_indicators(self.hub, self.other_user["id"]))
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

    async def test_actions_on_one_window_are_serialized_across_lines(self):
        self.db.create_conversation("child", "Child")
        self.db._exec("UPDATE conversations SET parent_id='alpha' WHERE id='child'")
        self.db._exec("UPDATE attachments SET conv_id='child' WHERE id='peer'")
        await self.grant("a")
        dispatched = []

        async def hold(message):  # the helper has the message but has not answered yet
            self.sent.append(message)
            dispatched.append(message)

        async def yield_to_loop():
            for _ in range(40):
                await asyncio.sleep(0)  # event-loop turns only; no real time passes

        def answer(message):
            self.hub.elements.receive(self.device, {"request_id": message["request_id"],
                                                    "status": "completed"})

        self.device["socket"].send_json = hold
        first = asyncio.create_task(self.act("a"))
        second = asyncio.create_task(self.act("peer"))
        await yield_to_loop()
        self.assertEqual(["window_element_action"], [m["type"] for m in dispatched])
        answer(dispatched[0])
        await yield_to_loop()
        self.assertEqual(2, len(dispatched), "the second dispatch waits for the first to finish")
        self.assertNotEqual(dispatched[0]["request_id"], dispatched[1]["request_id"])
        answer(dispatched[1])
        self.assertEqual([200, 200], [r.status_code for r in await asyncio.gather(first, second)])
        self.assertEqual({"a", "peer"}, {m["agent"] for m in dispatched})
        self.assertEqual({}, self.hub.elements.locks)  # the lock is dropped once nobody waits

    async def test_processes_on_a_line_share_one_snapshot_per_window(self):
        await self.grant("a")
        await self.grant("a", "Browser", "g2", 20)
        first = (await self.read("a", "g1")).json()
        again = (await self.read("peer", "g1")).json()
        self.assertEqual(first["snapshot_id"], again["snapshot_id"])
        self.assertEqual(1, sum(m["type"] == "read_window_elements" and m["grant_id"] == "g1"
                                for m in self.sent), "the second process reads the cached tree")
        await self.read("peer", "g2")
        self.assertEqual({"g1", "g2"}, set(self.hub.elements.snapshots))

    async def test_revoke_survives_helper_disconnect(self):
        await self.grant("a")
        self.device["socket"].send_json = AsyncMock(side_effect=RuntimeError("closed"))
        response = await self.client.delete("/api/screen/window-grants/g1", headers=self.human(self.owner))
        self.assertEqual(200, response.status_code)
        self.assertEqual(403, (await self.read("a")).status_code)
