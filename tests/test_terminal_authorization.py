"""Fixture-only regressions for terminal target and ongoing authority."""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from partyline.auth_store import create_user, ensure_api_token
from partyline.auth_tokens import create_access_token, signing_secret
from partyline.terminal_stream import terminal_endpoint
from tests import test_terminal_stream as fixtures
from tests.test_terminal_stream import (
    FakeTerminalAdapter, FakeWebSocket, eventually,
)


class TerminalAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.TerminalEndpointTest.setUp

    async def start_socket(self, token=None, att_id="att-1"):
        adapter = FakeTerminalAdapter()
        ws = FakeWebSocket(token=token or self.token)
        runtime = SimpleNamespace(live={att_id: adapter}, db=self.db)
        task = asyncio.create_task(terminal_endpoint(runtime)(ws, att_id))
        self.addAsyncCleanup(self.stop_task, task)
        await eventually(lambda: len(ws.sent) == 2 or ws.closed, "snapshot or refusal")
        return adapter, ws, task, runtime

    async def stop_task(self, task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def change(self, sql, args=()):
        self.db._exec(sql, args)

    async def assert_refused(self, ws, task, adapter, code=4403):
        await asyncio.wait_for(task, 2)
        self.assertEqual(ws.closed[0], code)
        self.assertEqual(adapter.writes, [])
        self.assertEqual(len(adapter.detached), 1)

    async def test_unrelated_machine_gets_no_geometry_snapshot_or_viewer(self):
        self.db.create_conversation("other", "Other")
        self.db.add_attachment("stranger", "other", "stranger", "fake", ["fake"], "/tmp")
        adapter, ws, task, _ = await self.start_socket(ensure_api_token(self.db, "stranger"))
        await asyncio.wait_for(task, 2)
        self.assertEqual(ws.closed[0], 4403)
        self.assertEqual(ws.sent, [])
        self.assertEqual(adapter.registry._queues, set())
        self.assertEqual(adapter.detached, [])

    async def test_read_only_machine_closes_on_input(self):
        self.change("UPDATE attachments SET is_lead=0 WHERE id='att-1'")
        adapter, ws, task, _ = await self.start_socket()
        adapter.registry.publish(b"view-only")
        await eventually(lambda: ("bytes", b"view-only") in ws.sent, "viewer output")
        ws.incoming.put_nowait("no")
        await self.assert_refused(ws, task, adapter)

    async def test_human_can_read_and_write(self):
        user = create_user(self.db, "human@example.test", "human", "unused")
        token = create_access_token(signing_secret(self.db), user["id"])
        adapter, ws, task, _ = await self.start_socket(token)
        adapter.registry.publish(b"human output")
        ws.incoming.put_nowait("human input")
        await eventually(lambda: bool(adapter.writes), "human input")
        await eventually(lambda: ("bytes", b"human output") in ws.sent, "human output")
        self.assertEqual(adapter.writes, [b"human input"])
        ws.incoming.put_nowait(None)
        await task

    async def test_expired_human_token_stops_input_with_reauthentication_code(self):
        user = create_user(self.db, "human@example.test", "human", "unused")
        adapter, ws, task, _ = await self.start_socket(
            create_access_token(signing_secret(self.db), user["id"]))
        # Advance JWT validation's clock beyond the real token's 30-minute life.
        with patch("jwt.api_jwt.datetime") as clock:
            clock.now.return_value = datetime.now(UTC) + timedelta(minutes=31)
            ws.incoming.put_nowait("denied")
            await self.assert_refused(ws, task, adapter, code=4401)
        self.assertEqual(len(ws.sent), 2)

    async def test_demotion_stops_input(self):
        adapter, ws, task, _ = await self.start_socket()
        self.change("UPDATE attachments SET is_lead=0 WHERE id='att-1'")
        ws.incoming.put_nowait("denied")
        await self.assert_refused(ws, task, adapter)

    async def test_revoked_token_stops_input(self):
        adapter, ws, task, _ = await self.start_socket()
        self.change("UPDATE attachments SET api_token=NULL WHERE id='att-1'")
        ws.incoming.put_nowait("denied")
        await self.assert_refused(ws, task, adapter, code=4401)

    async def test_revocation_blocks_already_queued_output(self):
        adapter, ws, task, _ = await self.start_socket()
        adapter.registry.publish(b"secret")
        self.change("UPDATE attachments SET api_token=NULL WHERE id='att-1'")
        await self.assert_refused(ws, task, adapter, code=4401)
        self.assertEqual(len(ws.sent), 2)

    async def test_idle_revocation_closes_without_input_or_output(self):
        with patch("partyline.terminal_stream.AUTH_CHECK_INTERVAL", 0.01):
            adapter, ws, task, _ = await self.start_socket()
            self.change("UPDATE attachments SET api_token=NULL WHERE id='att-1'")
            await self.assert_refused(ws, task, adapter, code=4401)

    async def test_deleted_target_stops_input(self):
        user = create_user(self.db, "human@example.test", "human", "unused")
        adapter, ws, task, _ = await self.start_socket(
            create_access_token(signing_secret(self.db), user["id"]))
        self.change("DELETE FROM attachments WHERE id='att-1'")
        ws.incoming.put_nowait("denied")
        await self.assert_refused(ws, task, adapter)

    async def test_moved_target_stops_input_even_for_human(self):
        user = create_user(self.db, "human@example.test", "human", "unused")
        adapter, ws, task, _ = await self.start_socket(
            create_access_token(signing_secret(self.db), user["id"]))
        self.db.create_conversation("other", "Other")
        self.change("UPDATE attachments SET conv_id='other' WHERE id='att-1'")
        ws.incoming.put_nowait("denied")
        await self.assert_refused(ws, task, adapter)

    async def test_revoked_between_geometry_and_snapshot_sends_no_snapshot(self):
        adapter = FakeTerminalAdapter()
        ws = FakeWebSocket(token=self.token)
        send = ws.send_text

        async def revoke_after_geometry(data):
            await send(data)
            self.change("UPDATE attachments SET api_token=NULL WHERE id='att-1'")

        ws.send_text = revoke_after_geometry
        await terminal_endpoint(SimpleNamespace(live={"att-1": adapter}, db=self.db))(ws, "att-1")
        self.assertEqual(ws.closed[0], 4401)
        self.assertEqual(ws.sent, [("text", '{"cols":120,"rows":40}')])
        self.assertEqual(len(adapter.detached), 1)

    async def test_idle_demotion_revokes_descendant_read(self):
        self.db.create_conversation("child", "Child")
        self.change("UPDATE conversations SET parent_id='line' WHERE id='child'")
        self.db.add_attachment("target", "child", "target", "fake", ["fake"], "/tmp")
        with patch("partyline.terminal_stream.AUTH_CHECK_INTERVAL", 0.01):
            adapter, ws, task, _ = await self.start_socket(att_id="target")
            self.change("UPDATE attachments SET is_lead=0 WHERE id='att-1'")
            await self.assert_refused(ws, task, adapter)

    async def test_replaced_live_adapter_stops_output(self):
        adapter, ws, task, runtime = await self.start_socket()
        runtime.live["att-1"] = FakeTerminalAdapter()
        adapter.registry.publish(b"old output")
        await self.assert_refused(ws, task, adapter)
        self.assertEqual(len(ws.sent), 2)


class WebSocketAuditGuardTest(unittest.TestCase):
    def test_registered_websocket_routes_are_exactly_the_audited_set(self):
        from starlette.routing import WebSocketRoute

        from partyline.server import app

        self.assertCountEqual(
            [route.path for route in app.routes if isinstance(route, WebSocketRoute)],
            ["/ws/{conv_id}", "/ws/attachments/{att_id}/terminal"],
            "Audit new WebSocket routes against their REST target checks first",
        )


if __name__ == "__main__":
    unittest.main()
