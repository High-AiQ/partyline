"""Exercise MCP's streamed upload against Partyline's actual HTTP parser."""

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from PIL import Image

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.media_routes import media_router
from partyline.mcp.client import ApiError, CHUNK, PartylineClient
from partyline.runtime import ChatRuntime


class MCPUploadRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/roundtrip.db")
        self.runtime = ChatRuntime(self.db)
        self.store = MediaStore(self.db, Path(self.directory.name) / "media")
        self.app = FastAPI()
        install_auth_guard(self.app, self.db)

        @self.app.post("/api/conversations/multipart-inspect/files")
        async def inspect_empty_multipart(request: Request):
            form = await request.form()
            file_part = form["file"]
            file_hex = (await file_part.read()).hex()
            fields = {name: form.get(name) for name in (
                "title", "description", "body", "client_key")}
            await form.close()
            return {
                "file_hex": file_hex,
                **fields,
            }

        self.app.include_router(media_router(self.runtime, self.store))
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        self.db.add_attachment("upload-a", "line", "uploader", "fake", ["fake"],
                               self.directory.name, "owner")
        self.db.set_attachment_status("upload-a", "running", "owner")
        self.token = auth_store.ensure_api_token(self.db, "upload-a")
        user = auth_store.create_user(
            self.db, "other@example.com", "other", auth_tokens.hash_password("test-password"))
        self.other_token = auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.close()
        self.server = uvicorn.Server(uvicorn.Config(
            self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.server.started:
            self.fail("isolated upload server did not start")

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.db.close()
        self.directory.cleanup()

    def client(self, token=None):
        client = PartylineClient.__new__(PartylineClient)
        client.connection = {
            "api": f"http://127.0.0.1:{self.port}",
            "token": token or self.token,
            "conversation_id": "line",
        }
        return client

    @staticmethod
    def png_bytes():
        from io import BytesIO

        output = BytesIO()
        Image.new("RGB", (2, 2), (20, 80, 160)).save(output, format="PNG")
        return output.getvalue()

    def upload_bytes(self, client, name, payload, key, *, conv_id="line", **metadata):
        path = Path(self.directory.name) / name
        path.write_bytes(payload)
        return client.upload(conv_id, str(path), client_key=key, **metadata)

    def download(self, client, file_ref):
        path = Path(self.directory.name) / ("download-" + file_ref["id"])
        client.download(file_ref["id"], "original", str(path))
        return path.read_bytes()

    def test_streamed_payloads_and_fields_roundtrip_through_production_parser(self):
        client = self.client()
        image = self.png_bytes()
        arbitrary = b"start\r\n--partyline-boundary-like\x00\xff\r\nend"
        cases = [
            ("text.txt", b"no final newline", "text-key"),
            ("binary.bin", arbitrary, "binary-key"),
            ("image.png", image, "image-key"),
            ("chunks.bin", b"chunk" * (CHUNK // 5 + 1000), "chunks-key"),
        ]
        for name, payload, key in cases:
            with self.subTest(name=name):
                response = self.upload_bytes(client, name, payload, key)
                self.assertEqual(self.download(client, response["files"][0]), payload)

        empty_metadata = {
            "title": "empty title", "description": "empty description",
            "body": "empty body",
        }
        parsed_empty = self.upload_bytes(
            client, "empty.bin", b"", "empty-inspect-key",
            conv_id="multipart-inspect", **empty_metadata,
        )
        self.assertEqual(bytes.fromhex(parsed_empty["file_hex"]), b"")
        for field, value in empty_metadata.items():
            self.assertEqual(parsed_empty[field], value)
        self.assertEqual(parsed_empty["client_key"], "empty-inspect-key")
        with self.assertRaisesRegex(ApiError, "a file upload cannot be empty"):
            self.upload_bytes(client, "empty.bin", b"", "empty-key", **empty_metadata)

        rich = self.upload_bytes(
            client, "metadata.txt", b"metadata bytes", "metadata-key",
            title="independent title", description="independent description",
            body="independent body",
        )
        self.assertEqual(rich["files"][0]["title"], "independent title")
        self.assertEqual(rich["files"][0]["description"], "independent description")
        self.assertEqual(rich["message"]["body"].splitlines()[0], "independent body")
        self.assertEqual(self.download(client, rich["files"][0]), b"metadata bytes")

        plain = self.upload_bytes(client, "plain.txt", b"only key", "plain-key")
        self.assertIsNone(plain["files"][0]["title"])
        self.assertIsNone(plain["files"][0]["description"])
        self.assertTrue(plain["message"]["body"].startswith("📎 plain.txt"))

    def test_retry_replays_once_and_client_and_destination_scope_stay_separate(self):
        client = self.client()
        first = self.upload_bytes(client, "retry.txt", b"original bytes", "stable-key",
                                  title="retry title", body="caption")
        replay = self.upload_bytes(client, "retry.txt", b"different bytes", "stable-key",
                                   title="changed", body="changed")
        self.assertEqual(replay["message"]["id"], first["message"]["id"])
        self.assertTrue(replay["message"]["replayed"])
        self.assertEqual(replay["files"][0]["id"], first["files"][0]["id"])
        self.assertEqual(self.db._exec("SELECT COUNT(*) FROM messages WHERE conv_id='line'")
                         .fetchone()[0], 1)
        self.assertEqual(self.db._exec("SELECT COUNT(*) FROM images WHERE conv_id='line'")
                         .fetchone()[0], 1)
        self.assertEqual(self.download(client, first["files"][0]), b"original bytes")

        other_caller = self.client(self.other_token)
        separate = self.upload_bytes(other_caller, "separate.txt", b"other caller",
                                     "stable-key")
        self.assertNotEqual(separate["message"]["id"], first["message"]["id"])
        other_line = self.upload_bytes(
            other_caller, "other-line.txt", b"other destination", "stable-key",
            conv_id="other",
        )
        self.assertNotEqual(other_line["message"]["id"], separate["message"]["id"])
        self.assertEqual(self.db._exec("SELECT COUNT(*) FROM messages WHERE conv_id='other'")
                         .fetchone()[0], 1)
        path = Path(self.directory.name) / "wrong-line.txt"
        path.write_bytes(b"wrong destination")
        with self.assertRaisesRegex(ApiError, "HTTP 403"):
            client.upload("other", str(path), client_key="stable-key")


if __name__ == "__main__":
    unittest.main()
