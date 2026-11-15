"""Screen refresh failures and owner caches do not affect chat delivery."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.contracts import ConversationsChangedEvent
from partyline.screen_snapshot import owner_state, refresh_snapshots
from tests.window_grant_fixtures import WindowGrantFixture


class ScreenSnapshotRefreshTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    def browser(self, owner_id):
        return Mock(screen_owner_id=owner_id, send_json=AsyncMock())

    async def test_hierarchy_refresh_builds_once_per_owner_across_lines_and_tabs(self):
        first, second, third = (self.browser(self.owner["id"]) for _ in range(3))
        other, anonymous = self.browser(self.other_user["id"]), self.browser(None)
        self.runtime.sockets = {"alpha": {first, second}, "beta": {third, other, anonymous}}
        with patch("partyline.screen_snapshot.owner_state", wraps=owner_state) as build:
            await self.runtime.broadcast_all(ConversationsChangedEvent())
        self.assertCountEqual([self.owner["id"], self.other_user["id"]],
                              [call.args[1] for call in build.call_args_list])
        for browser in (first, second, third):
            self.assertEqual("screen_snapshot", browser.send_json.call_args.args[0]["type"])
            self.assertEqual(self.device["id"], browser.send_json.call_args.args[0]["devices"][0]["id"])
        self.assertEqual([], other.send_json.call_args.args[0]["devices"])
        self.assertEqual([], other.send_json.call_args.args[0]["indicators"])
        anonymous.send_json.assert_awaited_once_with({"type": "conversations_changed"})

    async def test_build_view_and_send_failures_preserve_socket_handle_and_future_chat(self):
        for stage in ("build", "view", "send"):
            with self.subTest(stage=stage), ExitStack() as patches:
                browser = self.browser(self.owner["id"])
                self.runtime.sockets = {"alpha": {browser}}
                self.runtime.human_handles = {"alpha": {browser: ("owner", "tab")}}
                received = []

                async def send(payload, stage=stage, received=received):
                    if stage == "send" and payload["type"] == "screen_snapshot":
                        raise RuntimeError("snapshot send failed")
                    received.append(payload["type"])

                browser.send_json.side_effect = send
                if stage == "build":
                    patches.enter_context(patch("partyline.screen_snapshot.owner_state",
                                                side_effect=ValueError("snapshot build failed")))
                elif stage == "view":
                    patches.enter_context(patch("partyline.screen_snapshot.snapshot",
                                                side_effect=ValueError("snapshot view failed")))
                for _ in range(2):
                    await self.runtime.broadcast_all(ConversationsChangedEvent())
                self.assertEqual(["conversations_changed", "conversations_changed"], received)
                self.assertIn(browser, self.runtime.sockets["alpha"])
                self.assertEqual(("owner", "tab"), self.runtime.human_handles["alpha"][browser])

    async def test_failed_owner_build_is_cached_without_blocking_other_owners(self):
        first, second = self.browser(self.owner["id"]), self.browser(self.owner["id"])
        other = self.browser(self.other_user["id"])
        self.runtime.sockets = {"alpha": {first}, "beta": {second, other}}

        def build(hub, owner_id):
            if owner_id == self.owner["id"]:
                raise ValueError("unavailable owner state")
            return owner_state(hub, owner_id)

        with patch("partyline.screen_snapshot.owner_state", side_effect=build) as state:
            await self.runtime.broadcast_all(ConversationsChangedEvent())
        self.assertCountEqual([self.owner["id"], self.other_user["id"]],
                              [call.args[1] for call in state.call_args_list])
        first.send_json.assert_awaited_once_with({"type": "conversations_changed"})
        second.send_json.assert_awaited_once_with({"type": "conversations_changed"})
        self.assertEqual([], other.send_json.call_args.args[0]["devices"])

    async def test_refresh_without_screen_hub_is_a_noop(self):
        await refresh_snapshots(SimpleNamespace())
