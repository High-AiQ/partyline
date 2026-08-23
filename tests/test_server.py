import asyncio
from contextlib import asynccontextmanager, contextmanager
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, WebSocketDisconnect
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, bind, frontend_build, server
from partyline.auth_guard import Principal
from partyline.attachment_resume import TranscriptDeliveryRecord, delivered_history
from partyline.db import Db
from partyline.follow_routing import CATCH_UP_HEADER
from partyline.hook_routes import handle_hook
from partyline.presence import Presence
from partyline.preset_routes import presets_router
from partyline.restart_report import restart_report_router
from partyline.runtime import ChatRuntime
from partyline.tasks import TaskError


class FakeAdapter:
    def __init__(self, fail_start=False, fail_delivery=False, on_status=None, att=None):
        self.deliveries = []
        self.stopped = False
        self.fail_start = fail_start
        self.fail_delivery = fail_delivery
        self.on_status = on_status
        self.att = att or {}
        self.keys = []

    async def deliver(self, messages):
        if self.fail_delivery:
            raise RuntimeError("delivery rejected")
        self.deliveries.append(messages)

    def stage_startup_delivery(self, messages):
        return False

    async def wait_startup_delivery_received(self):
        return True

    async def start(self):
        if self.fail_start:
            raise RuntimeError("nope")
        if self.on_status:
            await self.on_status("running")

    async def stop(self):
        self.stopped = True
        if self.on_status:
            await self.on_status("detached")

    async def wait_ready(self):
        return True

    def screen_text(self):
        return "screen"

    def send_key(self, key):
        if key == "bad":
            raise ValueError("bad key")
        self.keys.append(key)


class ReplacingDeliveryAdapter(FakeAdapter):
    """Try to replace this activation at the first instruction of delivery."""

    def __init__(self, replacement, attachment_id, transition="stale", **kwargs):
        super().__init__(**kwargs)
        self.replacement = replacement
        self.attachment_id = attachment_id
        self.transition = transition
        self.lock_attempted = threading.Event()
        self.replacement_finished = threading.Event()
        self.replacement_crossed_before_write = False
        self.replacement_task = None

    def replace(self):
        original_guard = self.replacement._runtime_serialized

        @contextmanager
        def signalled_guard():
            self.lock_attempted.set()
            with original_guard():
                yield

        self.replacement._runtime_serialized = signalled_guard
        if self.transition == "stale":
            self.replacement.mark_stale_attachments()
        else:
            self.replacement.set_attachment_status(
                self.attachment_id, "exited", "old-generation"
            )
        self.replacement.claim_attachment(self.attachment_id, "new-generation")
        self.replacement.set_attachment_status(
            self.attachment_id, "running", "new-generation"
        )
        self.replacement_finished.set()

    async def deliver(self, messages):
        self.replacement_task = asyncio.create_task(asyncio.to_thread(self.replace))
        await asyncio.to_thread(self.lock_attempted.wait)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self.replacement_finished.wait), timeout=0.05
            )
        except TimeoutError:
            pass
        self.replacement_crossed_before_write = self.replacement_finished.is_set()
        self.deliveries.append(messages)


class JsonRequest:
    def __init__(self, payload=None, fails=False):
        self.payload = payload
        self.fails = fails

    async def json(self):
        if self.fails:
            raise ValueError("not json")
        return self.payload


class StreamWebSocket:
    def __init__(self, *payloads, token=""):
        self.payloads = list(payloads)
        self.sent = []
        self.closed = None
        self.headers = {}
        self.query_params = {"token": token} if token else {}

    async def accept(self):
        pass

    async def close(self, code, reason=""):
        self.closed = (code, reason)

    async def receive_json(self):
        if not self.payloads:
            raise WebSocketDisconnect()
        return self.payloads.pop(0)

    async def send_json(self, event):
        self.sent.append(event)


class BindConfigTest(unittest.TestCase):
    def test_resolve_bind_precedence_is_cli_then_env_then_config_then_default(self):
        self.assertEqual(bind.resolve_bind([], {}, {}), ("127.0.0.1", 8642))
        self.assertEqual(
            bind.resolve_bind([], {}, {"server": {"host": "config.test", "port": 7000}}),
            ("config.test", 7000),
        )
        self.assertEqual(
            bind.resolve_bind(
                [], {"PARTYLINE_HOST": "env.test", "PARTYLINE_PORT": "8000"},
                {"server": {"host": "config.test", "port": 7000}},
            ),
            ("env.test", 8000),
        )
        self.assertEqual(
            bind.resolve_bind(
                ["--host", "cli.test", "--port", "9000"],
                {"PARTYLINE_HOST": "env.test", "PARTYLINE_PORT": "8000"},
                {"server": {"host": "config.test", "port": 7000}},
            ),
            ("cli.test", 9000),
        )
        self.assertEqual(
            bind.resolve_bind(
                ["--host", "cli.test"],
                {"PARTYLINE_PORT": "8000"},
                {"server": {"host": "config.test", "port": 7000}},
            ),
            ("cli.test", 8000),
        )

    def test_resolve_bind_normalizes_host_whitespace_and_brackets(self):
        self.assertEqual(
            bind.resolve_bind([], {}, {"server": {"host": "  [::1]  "}}),
            ("::1", 8642),
        )
        with self.assertRaisesRegex(ValueError, "valid address"):
            bind.resolve_bind([], {}, {"server": {"host": "[::1"}})

    def test_resolve_bind_validates_config(self):
        with self.assertRaisesRegex(ValueError, "port"):
            bind.resolve_bind([], {}, {"server": {"port": 0}})
        with self.assertRaisesRegex(ValueError, "table"):
            bind.resolve_bind([], {}, {"server": "wrong"})

    def test_instance_name_precedence_is_cli_then_env_then_config_then_unset(self):
        self.assertIsNone(bind.resolve_instance_name([], {}, {}))
        config = {"instance": {"name": "Configured"}}
        self.assertEqual(bind.resolve_instance_name([], {}, config), "Configured")
        self.assertEqual(
            bind.resolve_instance_name([], {"PARTYLINE_INSTANCE_NAME": "Environment"}, config),
            "Environment",
        )
        self.assertEqual(
            bind.resolve_instance_name(
                ["--instance-name", "Command line"],
                {"PARTYLINE_INSTANCE_NAME": "Environment"},
                config,
            ),
            "Command line",
        )

    def test_instance_name_rejects_empty_values_and_a_non_table(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            bind.resolve_instance_name([], {}, {"instance": {"name": " "}})
        with self.assertRaisesRegex(ValueError, "table"):
            bind.resolve_instance_name([], {}, {"instance": "Cockpit"})

    def test_load_bind_config_reads_toml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partyline.toml"
            path.write_text("[server]\nhost = 'config.test'\nport = 7000\n", encoding="utf-8")
            with self.assertLogs("partyline.bind", level="INFO") as logs:
                self.assertEqual(
                    server.load_bind_config(path),
                    {"server": {"host": "config.test", "port": 7000}},
                )
            self.assertIn(str(path), logs.output[0])

    def test_config_without_server_table_does_not_shadow_user_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            fallback = home / ".config" / "partyline"
            fallback.mkdir(parents=True)
            (root / "partyline.toml").write_text("[other]\nvalue = true\n", encoding="utf-8")
            (fallback / "config.toml").write_text(
                "[server]\nhost = 'home.test'\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(Path, "home", return_value=home):
                    self.assertEqual(
                        server.load_bind_config(), {"server": {"host": "home.test"}}
                    )
            finally:
                os.chdir(previous)

    def test_config_argument_expands_user(self):
        parsed = server.parse_bind_args(["--config", "~/partyline.toml"])
        self.assertEqual(parsed.config, Path.home() / "partyline.toml")

    def test_load_bind_config_prefers_cwd_over_user_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            fallback = home / ".config" / "partyline"
            fallback.mkdir(parents=True)
            (fallback / "config.toml").write_text(
                "[server]\nhost = 'home.test'\n", encoding="utf-8"
            )
            (root / "partyline.toml").write_text(
                "[server]\nhost = 'cwd.test'\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(Path, "home", return_value=home):
                    self.assertEqual(
                        server.load_bind_config(), {"server": {"host": "cwd.test"}}
                    )
            finally:
                os.chdir(previous)

    def test_malformed_explicit_bind_config_refuses_with_runtime_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text("[server\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "could not read config file"):
                server.load_bind_config(path)

    def test_explicit_missing_bind_config_refuses_to_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                server.load_bind_config(Path(directory) / "missing.toml")

    def test_main_threads_resolved_bind_to_uvicorn_and_hooks(self):
        captured = {}

        class FakeServer:
            def __init__(self, config):
                captured["config"] = config

            def run(self):
                captured["ran"] = True

        old_bind = server.app.state.bind
        old_name = getattr(server.app.state, "instance_name", None)
        try:
            with patch.object(server, "load_dotenv"), patch.object(
                server.uvicorn, "Server", FakeServer
            ):
                server.main([
                    "--host", "example.test", "--port", "9000",
                    "--instance-name", "Test instance",
                ])
            self.assertEqual(captured["config"].host, "example.test")
            self.assertEqual(captured["config"].port, 9000)
            self.assertEqual(
                server._hook_url("attachment", server.app.state.bind, "token-9"),
                "http://example.test:9000/api/hooks/attachment/token-9",
            )
            self.assertEqual(server.app.state.instance_name, "Test instance")
            self.assertTrue(captured["ran"])
        finally:
            server.app.state.bind = old_bind
            server.app.state.instance_name = old_name

    def test_loopback_guard_handles_missing_and_ipv4_mapped_peers(self):
        with self.assertRaisesRegex(HTTPException, "process control"):
            server.require_loopback(FakeRequest(None))
        server.require_loopback(FakeRequest("::ffff:127.0.0.1"))

    def test_hook_url_formats_ipv6_bind(self):
        self.assertEqual(
            server._hook_url("attachment", server.BindConfig("::1", 9000), "token-9"),
            "http://[::1]:9000/api/hooks/attachment/token-9",
        )


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_runtime = server.runtime
        self.original_adapters = server.ADAPTERS.copy()
        self.original_metadata = server.ADAPTER_METADATA.copy()
        self.original_make_adapter = server.make_adapter
        server.runtime = ChatRuntime(Db(f"{self.directory.name}/partyline.db"))
        server.ADAPTERS.clear()
        server.ADAPTERS["fake"] = FakeAdapter
        server.ADAPTER_METADATA.clear()
        server.ADAPTER_METADATA["fake"] = {
            "command": ["fake"],
            "requires": [],
            "capabilities": {"resume": True},
        }
        server.make_adapter = lambda _, att, __, on_status, **kwargs: FakeAdapter(
            on_status=on_status, att=att
        )
        self.conv = server.runtime.db.create_conversation("line", "Line")

    def tearDown(self):
        server.runtime.db.close()
        server.runtime = self.original_runtime
        server.ADAPTERS.clear()
        server.ADAPTERS.update(self.original_adapters)
        server.ADAPTER_METADATA.clear()
        server.ADAPTER_METADATA.update(self.original_metadata)
        server.make_adapter = self.original_make_adapter
        self.directory.cleanup()

    def arun(self, coroutine):
        return asyncio.run(coroutine)

    def assert_http(self, status, coroutine):
        with self.assertRaises(HTTPException) as raised:
            self.arun(coroutine)
        self.assertEqual(raised.exception.status_code, status)

    def add_attachment(
        self, ident, name="terra", status="running", owner=None, follow=False
    ):
        server.runtime.db.add_attachment(
            ident, "line", name, "fake", ["fake"], self.directory.name, owner, follow)
        server.runtime.db.set_attachment_status(ident, status, owner)

    def user_token(self, handle="greg"):
        """Register a human account and return a live access token for it."""
        user = auth_store.create_user(
            server.runtime.db, f"{handle}@example.com", handle,
            auth_tokens.hash_password("hunter2222"))
        secret = auth_tokens.signing_secret(server.runtime.db)
        return auth_tokens.create_access_token(secret, user["id"])

    def principal_request(self, name="greg", kind="user"):
        """A request already past the guard, as every protected route sees."""
        return SimpleNamespace(state=SimpleNamespace(
            principal=Principal(kind=kind, name=name)))

    def test_route_mentions_all_punctuation_self_and_unreachable(self):
        self.add_attachment("one", "terra")
        self.add_attachment("two", "luna")
        self.add_attachment("gone", "gone", "exited")
        terra, luna = FakeAdapter(), FakeAdapter()
        server.runtime.live.update(one=terra, two=luna)
        message = server.runtime.db.add_message(
            "line", "greg", "human", "hello @terra. and @all")
        self.arun(server.runtime.route_mentions("line", message))
        self.assertEqual(len(terra.deliveries), 1)
        self.assertEqual(len(luna.deliveries), 1)
        self.assertEqual(server.runtime.db.get_attachment("one")["last_seen"], message["id"])
        self.assertEqual(server.runtime.db.get_attachment("two")["last_seen"], message["id"])

        before = len(terra.deliveries)
        self.arun(server.runtime.route_mentions(
            "line", {**message, "sender_type": "system", "body": "@terra"}))
        self.assertEqual(len(terra.deliveries), before)
        direct = server.runtime.db.add_message("line", "greg", "human", "@gone")
        self.arun(server.runtime.route_mentions("line", direct))
        self.assertIn(
            "nothing was delivered", server.runtime.db.list_messages("line")[-1]["body"])

    def test_route_mentions_accepts_normal_and_format_interrupted_grok(self):
        self.add_attachment("one", "grok")
        adapter = FakeAdapter()
        server.runtime.live["one"] = adapter

        for format_char in ("", "\u200b", "\u200d", "\u2060", "\ufeff"):
            with self.subTest(format_char=ascii(format_char)):
                body = f"hello @{format_char}grok"
                message = server.runtime.db.add_message(
                    "line", "greg", "human", body
                )
                self.arun(server.runtime.route_mentions("line", message))
                self.assertEqual(adapter.deliveries[-1][-1], message)
                self.assertEqual(message["body"], body)

    def test_follow_wakes_for_idle_human_and_bundles_agent_chatter(self):
        self.add_attachment("lead", "grok", owner="owner", follow=True)
        adapter = FakeAdapter(att={"runtime_owner": "owner"})
        presence = Presence(server.runtime)
        server.runtime.live["lead"] = presence.watch(
            adapter, "line", "lead", "receipt",
            *server.runtime.held_wake_hooks("line", "lead", "grok"),
        )

        skipped = server.runtime.db.add_message("line", "sol", "agent", "standing by")
        self.arun(server.runtime.route_mentions("line", skipped))
        self.assertEqual(adapter.deliveries, [])
        self.assertEqual(server.runtime.db.get_attachment("lead")["last_seen"], 0)
        self.assertEqual(presence.queue.held_count("lead"), 0)

        first = server.runtime.db.add_message("line", "greg", "human", "status update?")
        self.arun(server.runtime.route_mentions("line", first))
        header = {"sender": "partyline", "sender_type": "system", "body": CATCH_UP_HEADER}
        self.assertEqual(adapter.deliveries, [[header, skipped, first]])
        self.assertNotIn(
            CATCH_UP_HEADER,
            [message["body"] for message in server.runtime.db.list_messages("line")],
        )
        self.arun(presence.began("line", "lead", owner="owner"))

        own = server.runtime.db.add_message("line", "grok", "agent", "on it")
        self.arun(server.runtime.route_mentions("line", own))
        second = server.runtime.db.add_message("line", "sol", "agent", "finding")
        self.arun(server.runtime.route_mentions("line", second))
        third = server.runtime.db.add_message("line", "greg", "human", "anything else?")
        self.arun(server.runtime.route_mentions("line", third))
        self.assertEqual(adapter.deliveries, [[header, skipped, first]])
        self.assertEqual(presence.queue.held_ids("lead"), [second["id"], third["id"]])

        self.arun(presence.ended("line", "lead", owner="owner"))
        self.assertEqual(
            adapter.deliveries,
            [[header, skipped, first], [header, second, third]],
        )
        self.assertEqual(server.runtime.db.get_attachment("lead")["last_seen"], third["id"])
        self.assertFalse(presence.is_working("lead"))

    def test_a_direct_mention_pastes_while_a_follow_lead_is_working(self):
        self.add_attachment("lead", "grok", owner="owner", follow=True)
        adapter = FakeAdapter(att={"runtime_owner": "owner", "name": "grok"})
        presence = Presence(server.runtime)
        server.runtime.live["lead"] = presence.watch(
            adapter, "line", "lead", "receipt",
            *server.runtime.held_wake_hooks("line", "lead", "grok"),
        )
        first = server.runtime.db.add_message("line", "greg", "human", "status")
        self.arun(server.runtime.route_mentions("line", first))
        header = {"sender": "partyline", "sender_type": "system", "body": CATCH_UP_HEADER}
        self.assertEqual(adapter.deliveries, [[header, first]])
        self.arun(presence.began("line", "lead", owner="owner"))
        chatter = server.runtime.db.add_message("line", "sol", "agent", "finding")
        self.arun(server.runtime.route_mentions("line", chatter))
        self.assertEqual(adapter.deliveries, [[header, first]])
        stop = server.runtime.db.add_message("line", "sol", "agent", "@grok stop")
        self.arun(server.runtime.route_mentions("line", stop))
        self.assertEqual(adapter.deliveries[-1], [header, chatter, stop])
        self.assertEqual(server.runtime.db.get_attachment("lead")["last_seen"], stop["id"])
        self.assertEqual(presence.queue.held_ids("lead"), [])

    def test_inactive_follow_does_not_turn_chatter_into_a_failed_mention(self):
        self.add_attachment("lead", "grok", status="detached", follow=True)
        message = server.runtime.db.add_message("line", "greg", "human", "plain chatter")
        self.arun(server.runtime.route_mentions("line", message))
        self.assertEqual(server.runtime.db.list_messages("line"), [message])

    def test_failed_mention_delivery_does_not_advance_cursor(self):
        self.add_attachment("one", "terra")
        server.runtime.live["one"] = FakeAdapter(fail_delivery=True)
        message = server.runtime.db.add_message("line", "greg", "human", "@terra")

        with self.assertRaisesRegex(RuntimeError, "delivery rejected"):
            self.arun(server.runtime.route_mentions("line", message))

        self.assertEqual(server.runtime.db.get_attachment("one")["last_seen"], 0)

    def test_stale_adapter_callbacks_cannot_mutate_or_post_after_replacement(self):
        server.runtime.db.add_attachment(
            "old",
            "line",
            "opus",
            "fake",
            ["fake"],
            self.directory.name,
            "old-generation",
        )
        self.assertTrue(
            server.runtime.db.set_attachment_status(
                "old", "running", "old-generation"
            )
        )
        old_status = server.runtime.status_callback(
            "old", "line", "old-generation"
        )
        old_post = server.runtime.post_callback(
            "old", "line", "old-generation"
        )

        server.runtime.db.mark_stale_attachments()
        self.assertTrue(server.runtime.db.claim_attachment("old", "new-generation"))
        self.assertTrue(
            server.runtime.db.set_attachment_status(
                "old", "running", "new-generation"
            )
        )
        self.arun(old_status("detached"))
        self.arun(old_post("opus", "agent", "stale output"))
        stale_adapter = FakeAdapter(att={"runtime_owner": "old-generation"})
        server.runtime.live["old"] = stale_adapter
        mention = server.runtime.db.add_message(
            "line", "greg", "human", "@opus continue"
        )
        self.arun(server.runtime.route_mentions("line", mention))

        self.assertEqual(server.runtime.db.get_attachment("old")["status"], "running")
        self.assertEqual(server.runtime.db.get_attachment("old")["last_seen"], 0)
        self.assertEqual(stale_adapter.deliveries, [])
        self.assertEqual(server.runtime.db.list_messages("line"), [mention])

    def test_agent_speech_does_not_probe_cwd_git(self):
        self.add_attachment("one", "terra", owner="owner")
        with patch("partyline.attachment_view.subprocess.run") as git:
            self.arun(
                server.runtime.post_callback("one", "line", "owner")(
                    "terra", "agent", "done"
                )
            )
        git.assert_not_called()

    def test_resume_hatch_speech_is_visible_but_does_not_route_old_mentions(self):
        self.add_attachment("old", "grok", status="exited")
        self.add_attachment("target", "sol")
        target = FakeAdapter()
        server.runtime.live["target"] = target
        self.arun(server.resume_attachment("old"))
        resumed = server.runtime.live["old"]
        historical = "@sol do an obsolete task"

        self.arun(resumed.att["post_resume_record"]("grok", "agent", historical))
        self.assertEqual(target.deliveries, [])
        self.assertEqual(server.runtime.db.list_messages("line")[-1]["body"], historical)

        self.arun(server.runtime.post_callback(
            "old", "line", resumed.att["runtime_owner"]
        )("grok", "agent", historical))
        self.assertEqual(target.deliveries[-1][-1]["body"], historical)

    def test_replacement_cannot_cross_owner_validation_before_pty_delivery(self):
        server.runtime.db.add_attachment(
            "old",
            "line",
            "opus",
            "fake",
            ["fake"],
            self.directory.name,
            "old-generation",
        )
        self.assertTrue(
            server.runtime.db.set_attachment_status(
                "old", "running", "old-generation"
            )
        )
        replacement = Db(f"{self.directory.name}/partyline.db")
        adapter = ReplacingDeliveryAdapter(
            replacement,
            "old",
            att={"runtime_owner": "old-generation"},
        )
        server.runtime.live["old"] = adapter
        message = server.runtime.db.add_message(
            "line", "greg", "human", "@opus continue"
        )

        async def deliver_then_wait_for_replacement():
            await server.runtime.route_mentions("line", message)
            await adapter.replacement_task

        try:
            self.arun(deliver_then_wait_for_replacement())
            self.assertFalse(adapter.replacement_crossed_before_write)
            self.assertEqual(adapter.deliveries, [[message]])
            current = replacement.get_attachment("old")
            self.assertEqual(current["runtime_owner"], "new-generation")
            self.assertEqual(current["status"], "running")
        finally:
            replacement.close()

    def test_exit_cannot_make_attachment_claimable_during_pty_delivery(self):
        server.runtime.db.add_attachment(
            "old",
            "line",
            "opus",
            "fake",
            ["fake"],
            self.directory.name,
            "old-generation",
        )
        self.assertTrue(
            server.runtime.db.set_attachment_status(
                "old", "running", "old-generation"
            )
        )
        replacement = Db(f"{self.directory.name}/partyline.db")
        adapter = ReplacingDeliveryAdapter(
            replacement,
            "old",
            transition="exit",
            att={"runtime_owner": "old-generation"},
        )
        server.runtime.live["old"] = adapter
        message = server.runtime.db.add_message(
            "line", "greg", "human", "@opus continue"
        )

        async def deliver_then_wait_for_replacement():
            await server.runtime.route_mentions("line", message)
            await adapter.replacement_task

        try:
            self.arun(deliver_then_wait_for_replacement())
            self.assertFalse(adapter.replacement_crossed_before_write)
            self.assertEqual(adapter.deliveries, [[message]])
            current = replacement.get_attachment("old")
            self.assertEqual(current["runtime_owner"], "new-generation")
            self.assertEqual(current["status"], "running")
        finally:
            replacement.close()

    def test_real_status_callback_waits_for_active_mention_delivery(self):
        server.runtime.db.add_attachment(
            "old",
            "line",
            "opus",
            "fake",
            ["fake"],
            self.directory.name,
            "old-generation",
        )
        self.assertTrue(
            server.runtime.db.set_attachment_status(
                "old", "running", "old-generation"
            )
        )
        replacement = Db(f"{self.directory.name}/partyline.db")
        replacement_runtime = ChatRuntime(replacement)
        adapter = FakeAdapter(att={"runtime_owner": "old-generation"})
        server.runtime.live["old"] = adapter
        lock_attempted = asyncio.Event()
        transition_task = None
        transition_crossed_before_write = False
        original_async_guard = replacement._runtime_serialized_async

        @asynccontextmanager
        async def signalled_guard():
            lock_attempted.set()
            async with original_async_guard():
                yield

        replacement._runtime_serialized_async = signalled_guard

        async def exit_then_claim():
            await replacement_runtime.status_callback(
                "old", "line", "old-generation"
            )("exited")
            self.assertTrue(
                await replacement.claim_attachment_async("old", "new-generation")
            )
            self.assertTrue(
                await replacement.set_attachment_status_async(
                    "old", "running", "new-generation"
                )
            )

        async def deliver(messages):
            nonlocal transition_task, transition_crossed_before_write
            transition_task = asyncio.create_task(exit_then_claim())
            await lock_attempted.wait()
            await asyncio.sleep(0.02)
            transition_crossed_before_write = transition_task.done()
            adapter.deliveries.append(messages)

        adapter.deliver = deliver
        message = server.runtime.db.add_message(
            "line", "greg", "human", "@opus continue"
        )

        async def deliver_then_wait_for_transition():
            await server.runtime.route_mentions("line", message)
            await transition_task

        try:
            self.arun(deliver_then_wait_for_transition())
            self.assertFalse(transition_crossed_before_write)
            self.assertEqual(adapter.deliveries, [[message]])
            current = replacement.get_attachment("old")
            self.assertEqual(current["runtime_owner"], "new-generation")
            self.assertEqual(current["status"], "running")
        finally:
            replacement.close()

    def test_real_detach_route_waits_without_blocking_the_event_loop(self):
        server.runtime.db.add_attachment(
            "old",
            "line",
            "opus",
            "fake",
            ["fake"],
            self.directory.name,
            "old-generation",
        )
        self.assertTrue(
            server.runtime.db.set_attachment_status(
                "old", "exited", "old-generation"
            )
        )

        async def reserve_then_detach():
            async with server.runtime.db.reserve_attachment_delivery(
                "old", "old-generation"
            ) as reserved:
                self.assertTrue(reserved)
                lock_attempted = asyncio.Event()
                original_async_guard = server.runtime.db._runtime_serialized_async

                @asynccontextmanager
                async def signalled_guard():
                    lock_attempted.set()
                    async with original_async_guard():
                        yield

                server.runtime.db._runtime_serialized_async = signalled_guard
                detaching = asyncio.create_task(server.detach("old"))
                await lock_attempted.wait()
                await asyncio.sleep(0.02)
                self.assertFalse(detaching.done())
            await detaching

        self.arun(reserve_then_detach())
        self.assertEqual(server.runtime.db.get_attachment("old")["status"], "detached")
        self.assertEqual(
            server.runtime.db.list_messages("line")[-1]["body"], "@opus detached"
        )

    def test_websocket_stamps_the_credential_handle_and_ignores_client_senders(self):
        socket = StreamWebSocket(
            {"body": "too early"},
            {"type": "hello", "handle": "somebody-else"},
            {"sender": "luna", "body": "hello"},
            token=self.user_token("greg"),
        )
        old_name = getattr(server.app.state, "instance_name", None)
        server.app.state.instance_name = "Cockpit"
        try:
            self.arun(server.ws_endpoint(socket, "line"))
        finally:
            server.app.state.instance_name = old_name
        self.assertEqual([event["type"] for event in socket.sent], ["error", "hello", "message"])
        self.assertEqual(socket.sent[1]["build"], frontend_build.FRONTEND_BUILD)
        self.assertEqual(socket.sent[1]["version"], server.__version__)
        self.assertEqual(socket.sent[1]["instance_name"], "Cockpit")
        # The handle comes from the account, never the hello or message fields.
        self.assertEqual(socket.sent[1]["handle"], "greg")
        posted = server.runtime.db.list_messages("line")[-1]
        self.assertEqual((posted["sender"], posted["body"]), ("greg", "hello"))
        self.assertEqual(server.runtime.human_handles, {})

    def test_frontend_build_manifest_is_validated(self):
        manifest = Path(self.directory.name) / "build.json"
        manifest.write_text('{"build":"0123456789abcdef"}', encoding="utf-8")
        self.assertEqual(frontend_build.load_frontend_build(manifest), "0123456789abcdef")

        manifest.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "no valid frontend build manifest"):
            frontend_build.load_frontend_build(manifest)

        manifest.write_text('{"build":"not-a-digest"}', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "invalid frontend build id"):
            frontend_build.load_frontend_build(manifest)

    def test_current_frontend_build_follows_a_rebuild_without_a_restart(self):
        # A deploy swaps the bundle under a running server. `/assets` is a
        # StaticFiles mount and serves the new JavaScript immediately, so an id
        # captured at import would disagree with it forever and the client's
        # reload guard would loop.
        manifest = Path(self.directory.name) / "build.json"
        manifest.write_text('{"build":"0123456789abcdef"}', encoding="utf-8")
        with patch.object(frontend_build, "BUILD_MANIFEST", manifest):
            self.assertEqual(frontend_build.current_frontend_build(), "0123456789abcdef")
            manifest.write_text('{"build":"fedcba9876543210"}', encoding="utf-8")
            self.assertEqual(frontend_build.current_frontend_build(), "fedcba9876543210")
            self.assertEqual(self.arun(server.version())["build"], "fedcba9876543210")

            # A manifest that vanishes mid-run keeps the last good id: the
            # server is already running, which is better evidence the frontend
            # was valid than one failed read is that it is not.
            manifest.unlink()
            self.assertEqual(frontend_build.current_frontend_build(), "fedcba9876543210")

    def test_websocket_without_a_credential_is_closed_4401(self):
        socket = StreamWebSocket({"type": "hello"})
        self.arun(server.ws_endpoint(socket, "line"))
        self.assertEqual(socket.closed, (4401, "authentication required"))
        self.assertEqual(socket.sent, [])

    def test_machine_token_is_refused_on_the_chat_socket(self):
        """An attachment speaks through its harness, never as a chat human.

        Before this guard a machine token entered ``human_handles`` and its
        speech was stamped ``sender_type="human"`` — silent relabeling of an
        authenticated agent.
        """
        self.add_attachment("process", "opus")
        token = auth_store.ensure_api_token(server.runtime.db, "process")
        socket = StreamWebSocket(
            {"type": "hello"}, {"body": "beep"}, token=token)
        self.arun(server.ws_endpoint(socket, "line"))
        self.assertEqual(
            socket.closed,
            (4403, "machine tokens cannot join the chat socket"),
        )
        self.assertEqual(socket.sent, [])
        self.assertEqual(server.runtime.human_handles, {})
        self.assertEqual(server.runtime.db.list_messages("line"), [])

    def test_attach_rejects_handle_claimed_by_a_human(self):
        self.user_token("terra")
        self.assert_http(409, server.attach(self.principal_request(), "line", server.AttachIn(
            name="TERRA", adapter="fake", cwd=self.directory.name)))

    def test_matching_client_id_reclaims_a_stale_handle(self):
        stale_socket = object()
        server.runtime.sockets["line"] = {stale_socket}
        server.runtime.human_handles["line"] = {stale_socket: ("terra", "browser-id")}
        socket = StreamWebSocket(
            {"type": "hello", "client_id": "browser-id"},
            {"body": "back online"},
            token=self.user_token("terra"),
        )
        self.arun(server.ws_endpoint(socket, "line"))
        self.assertNotIn(stale_socket, server.runtime.sockets["line"])
        self.assertEqual(server.runtime.db.list_messages("line")[-1]["body"], "back online")

    def test_restart_failure_report_needs_the_plan_capability(self):
        """The watchdog's only credential is the plan's own report token."""
        gate_closed = []

        def loopback_gate(request):
            if gate_closed:
                raise HTTPException(403)

        app = FastAPI()
        app.include_router(restart_report_router(server.runtime, loopback_gate))
        client = TestClient(app)

        # No plan at all: nothing to authenticate against.
        self.assertEqual(404, client.post(
            "/api/restart-plan/failure",
            json={"token": "x", "message": "boom"}).status_code)

        plan = server.runtime.db.save_restart_plan("line", ["a1"], "Continue.")
        wrong = client.post(
            "/api/restart-plan/failure", json={"token": "nope", "message": "boom"})
        self.assertEqual(404, wrong.status_code)

        posted = client.post(
            "/api/restart-plan/failure",
            json={"token": plan["report_token"], "message": "trigger refused"})
        self.assertEqual(200, posted.status_code)
        last = server.runtime.db.list_messages("line")[-1]
        self.assertEqual("system", last["sender_type"])
        self.assertEqual("⚠ trigger refused", last["body"])

        # Loopback is belt-and-braces on top of the token, never instead.
        gate_closed.append(True)
        refused = client.post(
            "/api/restart-plan/failure",
            json={"token": plan["report_token"], "message": "boom"})
        self.assertEqual(403, refused.status_code)

    def test_topic_and_rename_validation_and_notices(self):
        request = self.principal_request("greg")
        self.assert_http(404, server.set_topic(request, "missing", server.TopicIn(topic="x")))
        self.assert_http(400, server.set_topic(request, "line", server.TopicIn(topic="x" * 3001)))
        changed = self.arun(server.set_topic(request, "line", server.TopicIn(topic=" New ")))
        self.assertEqual(changed["topic"], "New")
        self.assertIn(
            "topic set by @greg", server.runtime.db.list_messages("line")[-1]["body"])
        self.assert_http(400, server.rename_conversation(request, "line", server.RenameIn(name=" ")))
        self.assert_http(400, server.rename_conversation(request, "line", server.RenameIn(name="x" * 121)))
        renamed = self.arun(
            server.rename_conversation(request, "line", server.RenameIn(name="Renamed"))
        )
        self.assertEqual(renamed["name"], "Renamed")
        self.assertIn("Line → Renamed", server.runtime.db.list_messages("line")[-1]["body"])

    def test_archive_restore_purge_and_adapter_teardown(self):
        self.add_attachment("one")
        adapter = FakeAdapter()
        server.runtime.live["one"] = adapter
        archived = self.arun(server.archive_conversation("line"))
        self.assertTrue(archived["archived"])
        self.assertTrue(adapter.stopped)
        self.assertEqual(archived["stopped"], ["terra"])
        self.assert_http(409, server.archive_conversation("line"))
        restored = self.arun(server.restore_conversation("line"))
        self.assertIsNone(restored["archived_at"])
        self.assert_http(409, server.purge_conversation("line"))
        leftover = server.tasks.add("line", "must die with the line")
        self.arun(server.archive_conversation("line"))
        self.assertEqual(self.arun(server.purge_conversation("line")), {"ok": True, "purged": True})
        self.assertIsNone(server.runtime.db.get_conversation("line"))
        with self.assertRaises(TaskError):
            server.tasks.get(leftover["id"])

    def test_attach_validation_and_success(self):
        request = self.principal_request()
        self.assert_http(400, server.attach(
            request, "line", server.AttachIn(name="bad name", adapter="fake")
        ))
        self.assert_http(400, server.attach(
            request, "line", server.AttachIn(name="all", adapter="fake")
        ))
        self.assert_http(400, server.attach(
            request, "line", server.AttachIn(name="x", adapter="unknown")
        ))
        server.ADAPTER_METADATA["fake"]["requires"] = ["definitely-not-a-command"]
        self.assert_http(400, server.attach(
            request, "line", server.AttachIn(name="x", adapter="fake")
        ))
        server.ADAPTER_METADATA["fake"]["requires"] = []
        self.assert_http(
            400, server.attach(
                request, "line",
                server.AttachIn(name="x", adapter="fake", cwd="/no/such/cwd"),
            )
        )
        attached = self.arun(
            server.attach(
                request, "line",
                server.AttachIn(name="terra", adapter="fake", cwd=self.directory.name),
            )
        )
        self.assertEqual(attached["name"], "terra")
        self.assertIn(attached["id"], server.runtime.live)
        self.assert_http(
            409, server.attach(
                request, "line",
                server.AttachIn(name="TERRA", adapter="fake", cwd=self.directory.name),
            )
        )

    def test_follow_attach_is_human_receipt_only_and_names_the_lead(self):
        human = self.principal_request()
        machine = self.principal_request("worker", "machine")
        self.assert_http(403, server.attach(
            machine, "line", server.AttachIn(
                name="worker", adapter="fake", cwd=self.directory.name, follow=False
            ),
        ))
        self.assert_http(400, server.attach(
            human, "line", server.AttachIn(
                name="lead", adapter="fake", cwd=self.directory.name, follow=True
            ),
        ))

        server.ADAPTER_METADATA["fake"]["capabilities"]["turn_end"] = "receipt"
        self.assertEqual(self.arun(server.adapters())[0]["completion"], "receipt")
        lead = self.arun(server.attach(
            human, "line", server.AttachIn(
                name="lead", adapter="fake", cwd=self.directory.name, follow=True
            ),
        ))
        self.assertTrue(lead["follow"])
        with self.assertRaises(HTTPException) as raised:
            self.arun(server.attach(
                human, "line", server.AttachIn(
                    name="other", adapter="fake", cwd=self.directory.name, follow=True
                ),
            ))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("@lead", raised.exception.detail)

    def test_follow_patch_is_live_human_owned_and_broadcast(self):
        server.ADAPTER_METADATA["fake"]["capabilities"]["turn_end"] = "receipt"
        self.add_attachment("lead", "grok", follow=True)
        self.add_attachment("other", "sol")
        socket = StreamWebSocket()
        server.runtime.sockets["line"] = {socket}
        human = self.principal_request()

        with self.assertRaises(HTTPException) as raised:
            self.arun(server.edit_attachment(
                human, "other", server.AttachmentPatchRequest(follow=True)
            ))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("@grok", raised.exception.detail)
        self.assert_http(403, server.edit_attachment(
            self.principal_request("sol", "machine"), "lead",
            server.AttachmentPatchRequest(follow=False),
        ))

        cleared = self.arun(server.edit_attachment(
            human, "lead", server.AttachmentPatchRequest(follow=False)
        ))
        enabled = self.arun(server.edit_attachment(
            human, "other", server.AttachmentPatchRequest(follow=True)
        ))
        self.assertFalse(cleared["follow"])
        self.assertTrue(enabled["follow"])
        self.assertEqual(socket.sent[-1]["attachment"]["name"], "sol")

        del server.ADAPTER_METADATA["fake"]["capabilities"]["turn_end"]
        self.arun(server.edit_attachment(
            human, "other", server.AttachmentPatchRequest(follow=False)
        ))
        self.assert_http(400, server.edit_attachment(
            human, "lead", server.AttachmentPatchRequest(follow=True)
        ))

    def test_update_true_without_a_command_is_400_before_a_row_exists(self):
        before = server.runtime.db.list_attachments("line")
        self.assert_http(
            400,
            server.attach(
                self.principal_request(), "line",
                server.AttachIn(
                    name="probe", adapter="fake", cwd=self.directory.name, update=True
                ),
            ),
        )
        self.assertEqual(server.runtime.db.list_attachments("line"), before)

    def test_a_failed_update_still_attaches_and_posts_the_output(self):
        from partyline.adapter_update import UpdateResult, format_notice

        server.ADAPTER_METADATA["fake"]["update_command"] = ["fake-cli", "update"]

        async def fake_apply(post, conv_id, handle, argv, **kwargs):
            await post(
                conv_id, "system", "system",
                format_notice(handle, argv, UpdateResult(1, "already newest")),
            )
            return UpdateResult(1, "already newest")

        with patch("partyline.server.apply_update", side_effect=fake_apply):
            attached = self.arun(
                server.attach(
                    self.principal_request(), "line",
                    server.AttachIn(
                        name="probe", adapter="fake",
                        cwd=self.directory.name, update=True,
                    ),
                )
            )
        self.assertEqual(attached["name"], "probe")
        self.assertIn(attached["id"], server.runtime.live)
        bodies = [row["body"] for row in server.runtime.db.list_messages("line")]
        self.assertTrue(any("already newest" in body and "@probe" in body for body in bodies))

    def test_resume_does_not_run_an_update(self):
        server.ADAPTER_METADATA["fake"]["update_command"] = ["fake-cli", "update"]
        self.add_attachment("old", status="exited")
        with patch("partyline.adapter_update.default_runner") as runner:
            self.arun(server.resume_attachment("old"))
            runner.assert_not_called()

    def test_edit_inactive_attachment_command_updates_every_tab(self):
        self.add_attachment("old", status="detached")
        server.runtime.db.set_cli_session("old", "kept-session", None)
        socket = StreamWebSocket()
        server.runtime.sockets["line"] = {socket}

        updated = self.arun(server.edit_attachment(
            FakeRequest("127.0.0.1"),
            "old",
            server.AttachmentPatchRequest(command='fake --label "two words"'),
        ))

        self.assertEqual(updated["command"], ["fake", "--label", "two words"])
        self.assertEqual(updated["cli_session"], "kept-session")
        self.assertEqual(socket.sent[0]["type"], "attachment")
        self.assertEqual(socket.sent[0]["attachment"]["command"], updated["command"])

    def test_edit_attachment_command_is_local_and_inactive_only(self):
        self.add_attachment("old", status="detached")
        body = server.AttachmentPatchRequest(command="fake --changed")

        self.assert_http(
            403, server.edit_attachment(FakeRequest("10.0.0.7"), "old", body)
        )
        server.runtime.live["old"] = FakeAdapter()
        self.assert_http(
            409, server.edit_attachment(FakeRequest("127.0.0.1"), "old", body)
        )
        server.runtime.live.clear()
        server.runtime.db.set_attachment_status("old", "running", None)
        self.assert_http(
            409, server.edit_attachment(FakeRequest("127.0.0.1"), "old", body)
        )
        self.assert_http(
            404, server.edit_attachment(FakeRequest("127.0.0.1"), "missing", body)
        )

    def test_edit_attachment_command_shares_attach_validation(self):
        self.add_attachment("old", status="exited")
        request = FakeRequest("127.0.0.1")
        server.ADAPTER_METADATA["fake"]["requires"] = ["definitely-not-a-command"]
        self.assert_http(400, server.edit_attachment(
            request, "old", server.AttachmentPatchRequest(command="fake")
        ))
        server.ADAPTER_METADATA["fake"]["requires"] = []
        self.assert_http(400, server.edit_attachment(
            request, "old", server.AttachmentPatchRequest(command="fake 'unfinished")
        ))

    def test_resume_screen_keys_and_detach(self):
        self.add_attachment("old", status="exited")
        server.runtime.db.add_message("line", "terra", "agent", "already delivered")
        resumed = self.arun(server.resume_attachment("old"))
        self.assertEqual(resumed["status"], "running")
        adapter = server.runtime.live["old"]
        self.assertEqual(adapter.att["delivered_bodies"], ["already delivered"])
        server.runtime.db.add_owned_message(
            "old", adapter.att["runtime_owner"], "line", "terra", "agent", "late relay"
        )
        self.assertTrue(adapter.att["mark_transcript_delivery"](b"fingerprint", "late relay"))
        history = delivered_history(server.runtime.db, server.runtime.db.get_attachment("old"))
        self.assertEqual(history.transcript_records, [
            TranscriptDeliveryRecord(b"fingerprint", "late relay")
        ])
        self.assertEqual(self.arun(server.attachment_screen("old")), {"screen": "screen"})
        self.assertEqual(self.arun(server.attachment_key("old", server.KeyIn(key="x"))), {"ok": True})
        self.assertEqual(adapter.keys, ["x"])
        self.assert_http(400, server.attachment_key("old", server.KeyIn(key="bad")))
        self.assertEqual(self.arun(server.detach("old")), {"ok": True})
        self.assertTrue(adapter.stopped)
        self.assert_http(404, server.attachment_screen("old"))

    def test_a_clean_process_exit_leaves_the_attachment_resumable(self):
        self.add_attachment("old", status="running")
        adapter = FakeAdapter(att={"runtime_owner": None})
        server.runtime.live["old"] = adapter

        self.arun(server.runtime.status_callback("old", "line", None)("exited"))

        self.assertNotIn("old", server.runtime.live)
        self.assertEqual(server.runtime.db.get_attachment("old")["status"], "exited")
        resumed = self.arun(server.resume_attachment("old"))
        self.assertEqual(resumed["status"], "running")
        self.assertIn("old", server.runtime.live)

    def test_stale_server_cannot_detach_an_attachment_owned_elsewhere(self):
        server.runtime.db.add_attachment(
            "other-owner",
            "line",
            "worker",
            "fake",
            ["fake"],
            self.directory.name,
            "old-generation",
        )
        server.runtime.db.set_attachment_status(
            "other-owner", "running", "old-generation"
        )
        old_adapter = FakeAdapter(
            on_status=server.runtime.status_callback(
                "other-owner", "line", "old-generation"
            ),
            att={"runtime_owner": "old-generation"},
        )
        server.runtime.live["other-owner"] = old_adapter

        server.runtime.db.mark_stale_attachments()
        self.assertTrue(
            server.runtime.db.claim_attachment("other-owner", "new-generation")
        )
        self.assertTrue(
            server.runtime.db.set_attachment_status(
                "other-owner", "running", "new-generation"
            )
        )
        messages_before = server.runtime.db.list_messages("line")

        self.assert_http(409, server.detach("other-owner"))

        self.assertTrue(old_adapter.stopped)
        self.assertEqual(
            server.runtime.db.get_attachment("other-owner")["status"], "running"
        )
        self.assertEqual(server.runtime.db.list_messages("line"), messages_before)

    def test_presets_and_attention_hook(self):
        app = FastAPI()
        app.include_router(presets_router(server.runtime, server.ADAPTERS))
        client = TestClient(app)
        for invalid in (
            {"title": "", "name": "x", "adapter": "fake"},
            {"title": "t", "name": "bad name", "adapter": "fake"},
            {"title": "t", "name": "all", "adapter": "fake"},
            {"title": "t", "name": "x", "adapter": "unknown"},
        ):
            self.assertEqual(400, client.post("/api/presets", json=invalid).status_code)
        preset = client.post("/api/presets", json={
            "title": " My preset ", "name": "x", "adapter": "fake", "command": " run "
        }).json()
        self.assertEqual(preset["title"], "My preset")
        self.assertEqual(1, len(client.get("/api/presets").json()))
        missing = client.put("/api/presets/missing", json={
            "title": "x", "name": "x", "adapter": "fake"})
        self.assertEqual(404, missing.status_code)
        updated = client.put(f"/api/presets/{preset['id']}", json={
            "title": "New", "name": "x", "adapter": "fake"}).json()
        self.assertEqual(updated["title"], "New")
        self.assertEqual(
            {"ok": True}, client.delete(f"/api/presets/{preset['id']}").json())

        self.add_attachment("hook", owner="owner-1")
        self.arun(
            hook_event(
                "hook", "owner-1",
                JsonRequest({"hookEventName": "Notification", "message": "Permission needed"}),
            )
        )
        self.assertIn("needs attention", server.runtime.db.list_messages("line")[-1]["body"])
        count = len(server.runtime.db.list_messages("line"))
        self.arun(hook_event(
            "hook", "owner-1",
            JsonRequest({"hookEventName": "Notification", "title": "idle"}),
        ))
        self.assert_http(422, hook_event("hook", "owner-1", JsonRequest(fails=True)))
        self.assertEqual(len(server.runtime.db.list_messages("line")), count)

    def test_a_hook_without_the_current_activation_token_is_refused(self):
        """The attachment id is public; the hook must not be writable from it.

        It is printed in the join notice, used as the CLI session name, and
        now reachable from the whole LAN. A caller that guesses one is told
        404 either way, so this also does not confirm which ids exist.
        """
        self.add_attachment("hook", owner="owner-1")
        payload = JsonRequest(
            {"hookEventName": "Notification", "message": "Permission needed"}
        )
        count = len(server.runtime.db.list_messages("line"))

        self.assert_http(404, hook_event("hook", "owner-0", payload))
        self.assert_http(404, hook_event("hook", "", payload))
        self.assert_http(404, hook_event("missing", "owner-1", payload))
        self.assertEqual(len(server.runtime.db.list_messages("line")), count)

    def test_a_harness_turn_boundary_opens_and_closes_the_badge(self):
        """The receipt intake: paired hook events, nothing else."""
        self.add_attachment("hook", owner="owner-1")
        server.presence.register("hook", "receipt")
        self.arun(server.presence.started("line", "hook", owner="owner-1"))

        self.arun(hook_event("hook", "owner-1", JsonRequest({"hookEventName": "Stop"})))
        self.assertFalse(server.presence.is_working("hook"))
        server.presence.forget("hook")

    def test_a_grok_snake_case_stop_closes_the_badge(self):
        """Control: the dialect Grok actually POSTs. PascalCase is not enough."""
        self.add_attachment("hook", owner="owner-1")
        server.presence.register("hook", "receipt")
        self.arun(server.presence.started("line", "hook", owner="owner-1"))

        self.arun(hook_event("hook", "owner-1", JsonRequest({"hookEventName": "stop"})))
        self.assertFalse(server.presence.is_working("hook"))
        server.presence.forget("hook")

    def test_a_subagent_stop_is_not_the_parent_turn_ending(self):
        """@grok: a subagent finishing would clear the badge mid-work."""
        self.add_attachment("hook", owner="owner-1")
        self.arun(server.presence.started("line", "hook", owner="owner-1"))

        for name in ("SubagentStop", "Notification"):
            self.arun(hook_event("hook", "owner-1", JsonRequest({"hookEventName": name})))
        self.assertTrue(server.presence.is_working("hook"))
        for name in ("PreToolUse", "", None):
            self.assert_http(
                422, hook_event("hook", "owner-1", JsonRequest({"hookEventName": name}))
            )
        self.assertTrue(server.presence.is_working("hook"))
        server.presence.forget("hook")

    def test_a_receipt_from_another_session_cannot_close_this_turn(self):
        """A user-global hook fires for every session of that CLI on the box."""
        self.add_attachment("hook", owner="owner-1")
        self.arun(server.presence.started("line", "hook", owner="owner-1"))

        self.assert_http(
            404, hook_event("hook", "owner-9", JsonRequest({"hookEventName": "Stop"}))
        )
        self.assertTrue(server.presence.is_working("hook"))
        server.presence.forget("hook")

    def test_a_hook_body_that_is_not_json_is_422(self):
        self.add_attachment("hook", owner="owner-1")
        self.arun(server.presence.started("line", "hook", owner="owner-1"))

        self.assert_http(422, hook_event("hook", "owner-1", JsonRequest(fails=True)))
        self.assertTrue(server.presence.is_working("hook"))
        server.presence.forget("hook")

    def test_an_unknown_hook_event_is_422_not_a_dropped_receipt(self):
        self.add_attachment("hook", owner="owner-1")
        self.arun(server.presence.started("line", "hook", owner="owner-1"))
        self.assert_http(
            422,
            hook_event("hook", "owner-1", JsonRequest({"hookEventName": "PreToolUse"})),
        )
        self.assertTrue(server.presence.is_working("hook"))
        server.presence.forget("hook")

    def test_a_hook_for_a_superseded_activation_is_refused(self):
        """A resumed attachment gets a new owner; the old harness keeps firing."""
        self.add_attachment("hook", owner="owner-1", status="exited")
        self.assertTrue(server.runtime.db.claim_attachment("hook", "owner-2"))
        payload = JsonRequest(
            {"hookEventName": "Notification", "message": "Permission needed"}
        )

        self.assert_http(404, hook_event("hook", "owner-1", payload))
        self.arun(hook_event("hook", "owner-2", payload))
        self.assertIn("needs attention", server.runtime.db.list_messages("line")[-1]["body"])

    def test_an_attachment_with_no_activation_has_no_reachable_hook(self):
        self.add_attachment("hook")
        payload = JsonRequest(
            {"hookEventName": "Notification", "message": "Permission needed"}
        )

        self.assert_http(404, hook_event("hook", "", payload))

    def test_load_dotenv_and_hook_url(self):
        path = f"{self.directory.name}/.env"
        with open(path, "w") as dotenv:
            dotenv.write("NEW=value\nQUOTED=' hello '\n# ignored\nEXISTING=no\n")
        old_existing = os.environ.get("EXISTING")
        os.environ["EXISTING"] = "yes"
        old_bind = server.app.state.bind
        server.app.state.bind = server.BindConfig("example.test", 9999)
        try:
            server.load_dotenv(path)
            self.assertEqual(os.environ["NEW"], "value")
            self.assertEqual(os.environ["QUOTED"], " hello ")
            self.assertEqual(os.environ["EXISTING"], "yes")
            self.assertEqual(
                server._hook_url("attachment", server.app.state.bind, "token-9"),
                "http://example.test:9999/api/hooks/attachment/token-9",
            )
        finally:
            for key in ("NEW", "QUOTED"):
                os.environ.pop(key, None)
            if old_existing is None:
                os.environ.pop("EXISTING", None)
            else:
                os.environ["EXISTING"] = old_existing
            server.app.state.bind = old_bind


def hook_event(att_id, token, request):
    """The route handler, called directly rather than over HTTP."""
    return handle_hook(server.runtime, server.presence, att_id, token, request)


class FakeRequest:
    """Just enough Request for the shutdown route's caller check."""

    def __init__(self, host):
        self.client = type("Client", (), {"host": host})() if host else None


class ShutdownTest(ServerTest):
    def test_lifespan_starts_automatic_reattachment_without_a_browser(self):
        self.add_attachment("a1", "worker")
        server.runtime.db.save_restart_plan(
            "line", ["a1"], "Continue without a browser.", "automatic"
        )

        async def exercise():
            async with server.lifespan(server.app):
                await server.app.state.automatic_reattach_task
                self.assertIn("a1", server.runtime.live)
                self.assertIsNone(server.runtime.db.get_restart_plan())
                self.assertEqual(server.runtime.sockets, {})

        self.arun(exercise())

        bodies = [message["body"] for message in server.runtime.db.list_messages("line")]
        self.assertTrue(any("trusted cockpit plan started automatic" in body for body in bodies))

    def test_running_processes_lists_live_attachments_with_their_line(self):
        server.runtime.db.add_attachment("a1", "line", "worker", "fake", ["fake"], "/tmp")
        server.runtime.db.set_attachment_status("a1", "running", None)
        server.runtime.live["a1"] = FakeAdapter()

        running = self.arun(server.running())

        self.assertEqual(running, [{"name": "worker", "adapter": "fake", "conversation": "Line"}])

    def test_a_detached_attachment_is_not_reported_as_running(self):
        server.runtime.db.add_attachment("a1", "line", "worker", "fake", ["fake"], "/tmp")
        server.runtime.db.set_attachment_status("a1", "exited", None)

        self.assertEqual(self.arun(server.running()), [])

    def test_shutdown_is_refused_from_a_non_loopback_caller(self):
        """The bind address is configurable, so the caller must be checked."""
        exits = []
        original, server.request_exit = server.request_exit, lambda: exits.append(True)
        try:
            self.assert_http(403, server.shutdown(FakeRequest("10.0.0.7")))
            self.assertEqual(exits, [], "a refused shutdown must not stop the server")
        finally:
            server.request_exit = original

    def test_shutdown_reports_what_it_will_stop_and_warns_every_socket(self):
        server.runtime.db.add_attachment("a1", "line", "worker", "fake", ["fake"], "/tmp")
        server.runtime.db.set_attachment_status("a1", "running", None)
        server.runtime.live["a1"] = FakeAdapter()
        socket = StreamWebSocket([])
        server.runtime.sockets["line"] = {socket}

        response = self.arun(server.shutdown(FakeRequest("127.0.0.1")))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"stopping":["worker"]', response.body)
        # Every open tab hears about it before the process goes away.
        self.assertEqual(socket.sent, [{"type": "shutdown"}])
        # And the exit is deferred until after the response is flushed.
        self.assertIsNotNone(response.background)

    def test_restart_plan_is_local_line_scoped_and_only_includes_resumable_live_processes(self):
        self.add_attachment("a1", "worker")
        self.add_attachment("dead", "dead", "exited")
        server.runtime.live["a1"] = FakeAdapter()

        planned = self.arun(
            server.plan_restart(
                FakeRequest("127.0.0.1"),
                server.RestartPlanRequest(
                    conversation_id="line",
                    debrief="Continue the interrupted review.",
                ),
            )
        )

        self.assertEqual([attachment.id for attachment in planned.attachments], ["a1"])
        self.assertEqual(planned.conversation_id, "line")
        self.assert_http(
            403,
            server.plan_restart(
                FakeRequest("10.0.0.7"),
                server.RestartPlanRequest(conversation_id="line"),
            ),
        )

    def test_requesting_line_gets_offer_and_can_accept_sequential_reattachment(self):
        self.add_attachment("a1", "worker")
        server.runtime.live["a1"] = FakeAdapter()
        planned = server.save_restart_plan(
            server.RestartPlanRequest(conversation_id="line", debrief="Finish the review.")
        )
        server.runtime.live.clear()
        server.runtime.db.mark_stale_attachments()
        socket = StreamWebSocket(
            {"type": "hello", "client_id": "browser"},
            {"type": "reattach", "token": planned.token, "action": "accept"},
            token=self.user_token("greg"),
        )

        self.arun(server.ws_endpoint(socket, "line"))

        event_types = [event["type"] for event in socket.sent]
        self.assertIn("reattach_offer", event_types)
        self.assertIn("reattach_decision", event_types)
        self.assertIn("a1", server.runtime.live)
        self.assertIsNone(server.runtime.db.get_restart_plan())
        self.assertIn(
            "sequential reattachment finished",
            server.runtime.db.list_messages("line")[-1]["body"],
        )

    def test_other_lines_never_receive_or_consume_a_restart_offer(self):
        self.add_attachment("a1", "worker")
        server.runtime.live["a1"] = FakeAdapter()
        planned = server.save_restart_plan(
            server.RestartPlanRequest(conversation_id="line", debrief="Continue.")
        )
        server.runtime.db.create_conversation("other", "Other")
        socket = StreamWebSocket(
            {"type": "hello", "client_id": "browser"},
            {"type": "reattach", "token": planned.token, "action": "accept"},
            token=self.user_token("greg"),
        )

        self.arun(server.ws_endpoint(socket, "other"))

        self.assertNotIn("reattach_offer", [event["type"] for event in socket.sent])
        self.assertEqual(socket.sent[-1]["type"], "error")
        self.assertIsNotNone(server.runtime.db.get_restart_plan())

    def test_shutdown_asks_the_server_to_exit_rather_than_killing_the_process(self):
        """A hard exit would skip lifespan teardown and orphan every pty."""
        class FakeServer:
            should_exit = False

        original, server._uvicorn_server = server._uvicorn_server, FakeServer()
        try:
            server.request_exit()
            self.assertTrue(server._uvicorn_server.should_exit)
        finally:
            server._uvicorn_server = original
