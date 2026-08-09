import asyncio
from contextlib import asynccontextmanager, contextmanager
import os
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import HTTPException, WebSocketDisconnect

from partyline import server
from partyline.db import Db
from partyline.runtime import ChatRuntime


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
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.sent = []

    async def accept(self):
        pass

    async def receive_json(self):
        if not self.payloads:
            raise WebSocketDisconnect()
        return self.payloads.pop(0)

    async def send_json(self, event):
        self.sent.append(event)


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

    def add_attachment(self, ident, name="terra", status="running"):
        server.runtime.db.add_attachment(
            ident, "line", name, "fake", ["fake"], self.directory.name)
        server.runtime.db.set_attachment_status(ident, status, None)

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

    def test_websocket_claims_handle_before_messages_and_blocks_impersonation(self):
        socket = StreamWebSocket(
            {"sender": "terra", "body": "too early"},
            {"type": "hello", "handle": "terra"},
            {"sender": "luna", "body": "not mine"},
            {"sender": "terra", "body": "hello"},
        )
        self.arun(server.ws_endpoint(socket, "line"))
        self.assertEqual([event["type"] for event in socket.sent], ["error", "hello", "error", "message"])
        self.assertEqual(socket.sent[1]["build"], server.FRONTEND_BUILD)
        self.assertEqual(socket.sent[1]["version"], server.__version__)
        self.assertEqual(server.runtime.db.list_messages("line")[-1]["body"], "hello")
        self.assertEqual(server.runtime.human_handles, {})

    def test_frontend_build_manifest_is_validated(self):
        manifest = Path(self.directory.name) / "build.json"
        manifest.write_text('{"build":"0123456789abcdef"}', encoding="utf-8")
        self.assertEqual(server.load_frontend_build(manifest), "0123456789abcdef")

        manifest.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "no valid frontend build manifest"):
            server.load_frontend_build(manifest)

        manifest.write_text('{"build":"not-a-digest"}', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "invalid frontend build id"):
            server.load_frontend_build(manifest)

    def test_websocket_claim_rejects_invalid_duplicate_and_process_handles(self):
        self.add_attachment("process", "opus")
        server.runtime.human_handles["line"] = {object(): ("terra", "other-browser")}
        for handle, expected in (("bad name", "alphanumeric"), ("all", "reserved"),
                                 ("TERRA", "another human"), ("opus", "running process")):
            socket = StreamWebSocket({"type": "hello", "handle": handle})
            self.arun(server.ws_endpoint(socket, "line"))
            self.assertEqual(socket.sent[0]["type"], "error")
            self.assertIn(expected, socket.sent[0]["message"])

    def test_attach_rejects_handle_claimed_by_a_human(self):
        server.runtime.human_handles["line"] = {object(): ("terra", "other-browser")}
        self.assert_http(409, server.attach("line", server.AttachIn(
            name="TERRA", adapter="fake", cwd=self.directory.name)))

    def test_matching_client_id_reclaims_a_stale_handle(self):
        stale_socket = object()
        server.runtime.sockets["line"] = {stale_socket}
        server.runtime.human_handles["line"] = {stale_socket: ("terra", "browser-id")}
        socket = StreamWebSocket(
            {"type": "hello", "handle": "terra", "client_id": "browser-id"},
            {"sender": "terra", "body": "back online"},
        )
        self.arun(server.ws_endpoint(socket, "line"))
        self.assertNotIn(stale_socket, server.runtime.sockets["line"])
        self.assertEqual(server.runtime.db.list_messages("line")[-1]["body"], "back online")

    def test_topic_and_rename_validation_and_notices(self):
        self.assert_http(404, server.set_topic("missing", server.TopicIn(topic="x")))
        self.assert_http(400, server.set_topic("line", server.TopicIn(topic="x" * 3001)))
        changed = self.arun(server.set_topic("line", server.TopicIn(topic=" New ", sender=" greg ")))
        self.assertEqual(changed["topic"], "New")
        self.assertIn(
            "topic set by @greg", server.runtime.db.list_messages("line")[-1]["body"])
        self.assert_http(400, server.rename_conversation("line", server.RenameIn(name=" ")))
        self.assert_http(400, server.rename_conversation("line", server.RenameIn(name="x" * 121)))
        renamed = self.arun(
            server.rename_conversation("line", server.RenameIn(name="Renamed", sender="greg"))
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
        self.arun(server.archive_conversation("line"))
        self.assertEqual(self.arun(server.purge_conversation("line")), {"ok": True, "purged": True})
        self.assertIsNone(server.runtime.db.get_conversation("line"))

    def test_attach_validation_and_success(self):
        self.assert_http(400, server.attach("line", server.AttachIn(name="bad name", adapter="fake")))
        self.assert_http(400, server.attach("line", server.AttachIn(name="all", adapter="fake")))
        self.assert_http(400, server.attach("line", server.AttachIn(name="x", adapter="unknown")))
        server.ADAPTER_METADATA["fake"]["requires"] = ["definitely-not-a-command"]
        self.assert_http(400, server.attach("line", server.AttachIn(name="x", adapter="fake")))
        server.ADAPTER_METADATA["fake"]["requires"] = []
        self.assert_http(
            400, server.attach("line", server.AttachIn(name="x", adapter="fake", cwd="/no/such/cwd"))
        )
        attached = self.arun(
            server.attach("line", server.AttachIn(name="terra", adapter="fake", cwd=self.directory.name))
        )
        self.assertEqual(attached["name"], "terra")
        self.assertIn(attached["id"], server.runtime.live)
        self.assert_http(
            409, server.attach("line", server.AttachIn(name="TERRA", adapter="fake", cwd=self.directory.name))
        )

    def test_edit_inactive_attachment_command_updates_every_tab(self):
        self.add_attachment("old", status="detached")
        server.runtime.db.set_cli_session("old", "kept-session", None)
        socket = StreamWebSocket()
        server.runtime.sockets["line"] = {socket}

        updated = self.arun(server.edit_attachment_command(
            FakeRequest("127.0.0.1"),
            "old",
            server.AttachmentCommandRequest(command='fake --label "two words"'),
        ))

        self.assertEqual(updated["command"], ["fake", "--label", "two words"])
        self.assertEqual(updated["cli_session"], "kept-session")
        self.assertEqual(socket.sent[0]["type"], "attachment")
        self.assertEqual(socket.sent[0]["attachment"]["command"], updated["command"])

    def test_edit_attachment_command_is_local_and_inactive_only(self):
        self.add_attachment("old", status="detached")
        body = server.AttachmentCommandRequest(command="fake --changed")

        self.assert_http(
            403, server.edit_attachment_command(FakeRequest("10.0.0.7"), "old", body)
        )
        server.runtime.live["old"] = FakeAdapter()
        self.assert_http(
            409, server.edit_attachment_command(FakeRequest("127.0.0.1"), "old", body)
        )
        server.runtime.live.clear()
        server.runtime.db.set_attachment_status("old", "running", None)
        self.assert_http(
            409, server.edit_attachment_command(FakeRequest("127.0.0.1"), "old", body)
        )
        self.assert_http(
            404, server.edit_attachment_command(FakeRequest("127.0.0.1"), "missing", body)
        )

    def test_edit_attachment_command_shares_attach_validation(self):
        self.add_attachment("old", status="exited")
        request = FakeRequest("127.0.0.1")
        server.ADAPTER_METADATA["fake"]["requires"] = ["definitely-not-a-command"]
        self.assert_http(400, server.edit_attachment_command(
            request, "old", server.AttachmentCommandRequest(command="fake")
        ))
        server.ADAPTER_METADATA["fake"]["requires"] = []
        self.assert_http(400, server.edit_attachment_command(
            request, "old", server.AttachmentCommandRequest(command="fake 'unfinished")
        ))

    def test_resume_screen_keys_and_detach(self):
        self.add_attachment("old", status="exited")
        resumed = self.arun(server.resume_attachment("old"))
        self.assertEqual(resumed["status"], "running")
        adapter = server.runtime.live["old"]
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
        self.assert_http(400, server.create_preset(server.PresetIn(title="", name="x", adapter="fake")))
        preset = self.arun(
            server.create_preset(
                server.PresetIn(title=" My preset ", name="x", adapter="fake", command=" run ")
            )
        )
        self.assertEqual(preset["title"], "My preset")
        self.assert_http(
            404, server.update_preset("missing", server.PresetIn(title="x", name="x", adapter="fake"))
        )
        updated = self.arun(
            server.update_preset(preset["id"], server.PresetIn(title="New", name="x", adapter="fake"))
        )
        self.assertEqual(updated["title"], "New")
        self.assertEqual(self.arun(server.delete_preset(preset["id"])), {"ok": True})

        self.add_attachment("hook")
        self.arun(server.hook_event("hook", JsonRequest({"message": "Permission needed"})))
        self.assertIn("needs attention", server.runtime.db.list_messages("line")[-1]["body"])
        count = len(server.runtime.db.list_messages("line"))
        self.arun(server.hook_event("hook", JsonRequest({"title": "idle"})))
        self.arun(server.hook_event("hook", JsonRequest(fails=True)))
        self.assertEqual(len(server.runtime.db.list_messages("line")), count)

    def test_load_dotenv_and_hook_url(self):
        path = f"{self.directory.name}/.env"
        with open(path, "w") as dotenv:
            dotenv.write("NEW=value\nQUOTED=' hello '\n# ignored\nEXISTING=no\n")
        old_existing = os.environ.get("EXISTING")
        old_host = os.environ.get("PARTYLINE_HOST")
        old_port = os.environ.get("PARTYLINE_PORT")
        os.environ["EXISTING"] = "yes"
        os.environ["PARTYLINE_HOST"] = "example.test"
        os.environ["PARTYLINE_PORT"] = "9999"
        try:
            server.load_dotenv(path)
            self.assertEqual(os.environ["NEW"], "value")
            self.assertEqual(os.environ["QUOTED"], " hello ")
            self.assertEqual(os.environ["EXISTING"], "yes")
            self.assertEqual(server._hook_url("attachment"), "http://example.test:9999/api/hooks/attachment")
        finally:
            for key in ("NEW", "QUOTED"):
                os.environ.pop(key, None)
            if old_existing is None:
                os.environ.pop("EXISTING", None)
            else:
                os.environ["EXISTING"] = old_existing
            if old_host is None:
                os.environ.pop("PARTYLINE_HOST", None)
            else:
                os.environ["PARTYLINE_HOST"] = old_host
            if old_port is None:
                os.environ.pop("PARTYLINE_PORT", None)
            else:
                os.environ["PARTYLINE_PORT"] = old_port


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
            {"type": "hello", "handle": "greg", "client_id": "browser"},
            {"type": "reattach", "token": planned.token, "action": "accept"},
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
            {"type": "hello", "handle": "greg", "client_id": "browser"},
            {"type": "reattach", "token": planned.token, "action": "accept"},
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
