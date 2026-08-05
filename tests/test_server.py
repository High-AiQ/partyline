import asyncio
import os
import tempfile
import unittest

from fastapi import HTTPException, WebSocketDisconnect

from partyline import server
from partyline.db import Db
from partyline.runtime import ChatRuntime


class FakeAdapter:
    def __init__(self, fail_start=False):
        self.deliveries = []
        self.stopped = False
        self.fail_start = fail_start
        self.keys = []

    async def deliver(self, messages):
        self.deliveries.append(messages)

    async def start(self):
        if self.fail_start:
            raise RuntimeError("nope")

    async def stop(self):
        self.stopped = True

    def screen_text(self):
        return "screen"

    def send_key(self, key):
        if key == "bad":
            raise ValueError("bad key")
        self.keys.append(key)


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
        server.make_adapter = lambda *args, **kwargs: FakeAdapter()
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
        server.runtime.db.set_attachment_status(ident, status)

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

    def test_websocket_claims_handle_before_messages_and_blocks_impersonation(self):
        socket = StreamWebSocket(
            {"sender": "terra", "body": "too early"},
            {"type": "hello", "handle": "terra"},
            {"sender": "luna", "body": "not mine"},
            {"sender": "terra", "body": "hello"},
        )
        self.arun(server.ws_endpoint(socket, "line"))
        self.assertEqual([event["type"] for event in socket.sent], ["error", "hello", "error", "message"])
        self.assertEqual(server.runtime.db.list_messages("line")[-1]["body"], "hello")
        self.assertEqual(server.runtime.human_handles, {})

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

    def test_resume_screen_keys_and_detach(self):
        self.add_attachment("old", status="exited")
        resumed = self.arun(server.resume_attachment("old"))
        self.assertEqual(resumed["status"], "exited")
        adapter = server.runtime.live["old"]
        self.assertEqual(self.arun(server.attachment_screen("old")), {"screen": "screen"})
        self.assertEqual(self.arun(server.attachment_key("old", server.KeyIn(key="x"))), {"ok": True})
        self.assertEqual(adapter.keys, ["x"])
        self.assert_http(400, server.attachment_key("old", server.KeyIn(key="bad")))
        self.assertEqual(self.arun(server.detach("old")), {"ok": True})
        self.assertTrue(adapter.stopped)
        self.assert_http(404, server.attachment_screen("old"))

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
