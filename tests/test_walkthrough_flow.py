"""Scripted helper and recognizer exercise the in-memory take through upload."""
import io
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from PIL import Image

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.asr_presets import AsrRegistry
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.media_routes import media_router
from partyline.runtime import ChatRuntime
from partyline.screen_routes import register_screen_routes
from partyline.transcribe_routes import transcribe_router
from partyline.transcript import TakeFailed, Transcript
from tests.screen_helper_fakes import FakeDesktop
from tests.test_screen_share import png


class WalkthroughFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.tmp.name}/test.db")
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("bot", "line", "bot", "fake", ["fake"], "/tmp", "owner")
        self.db.set_attachment_status("bot", "running", "owner")
        self.runtime = ChatRuntime(self.db)
        self.runtime.route_mentions = AsyncMock()
        self.store = MediaStore(self.db, Path(self.tmp.name) / "media")
        app = FastAPI()
        install_auth_guard(app, self.db)
        self.hub = register_screen_routes(app, self.runtime, self.store)
        self.backend = SimpleNamespace(
            kind="fake", status=lambda: {"available": True, "reason": None, "model": None},
            transcribe=lambda *_: Transcript("click gear", "en", 3, (
                {"start": 0, "end": 1, "text": "click gear"},)))
        registry = AsrRegistry([("fake", self.backend)], max_bytes=1000)
        app.include_router(transcribe_router(self.runtime, lambda: registry))
        app.include_router(media_router(self.runtime, self.store))
        self.client = TestClient(app)
        self.client.__enter__()
        user = auth_store.create_user(self.db, "a@example.com", "alice",
                                      auth_tokens.hash_password("password1"))
        self.client.headers["Authorization"] = "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])
        code = self.client.post("/api/screen/pair?conv_id=line").json()["code"]
        self.device = self.client.post("/api/screen/pair/claim", json={
            "code": code, "device_name": "desk", "os": "test"}).json()
        self.now = 0.0
        self.hub.walkthroughs.clock = lambda: self.now

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.close()
        self.tmp.cleanup()

    def sync(self, ws):
        ws.send_json({"type": "ping"})
        self.assertEqual(ws.receive_json()["type"], "pong")

    def start(self, ws, captured=False):
        ws.send_json({"type": "hello", "protocol": 1, "device_name": "desk", "os": "test",
                      "helper_version": "1", "monitors": FakeDesktop().monitors()})
        self.sync(ws)
        region = {"x": -100, "y": 0, "width": 100, "height": 100}
        response = self.client.post("/api/screen/shares?conv_id=line", json={
            "device_id": self.device["device_id"], "region": region, "walkthrough": True})
        self.assertEqual(response.status_code, 200, response.text)
        share = ws.receive_json()["share_id"]
        ws.send_json({"type": "share_accepted", "share_id": share})
        self.sync(ws)
        path = f"/api/conversations/line/walkthroughs/{share}"
        status = self.client.get("/api/screen/shares?conv_id=line").json()["share"]
        self.assertTrue(status["walkthrough"])
        self.assertFalse(status["recording"])
        self.assertEqual(self.client.post(path + "/arm").status_code, 200)
        self.assertTrue(self.client.get("/api/screen/shares?conv_id=line").json()["share"]["recording"])
        self.assertEqual(self.client.post("/api/conversations/line/screen-frame").status_code, 409)
        self.assertEqual(self.client.post("/api/conversations/line/files", data={
            "include_screen": "true"}).status_code, 409)
        for i in range(25):
            self.now = i
            ws.send_json({"type": "frame", "share_id": share, "request_id": None,
                          "ts_ms": i, "region": region, "out_width": 32, "out_height": 24,
                          "pointer": {"x": -50, "y": 50, "visible": True, "captured": captured},
                          "mime": "image/png"})
            ws.send_bytes(png("red" if i % 2 else "blue"))
            self.sync(ws)
        self.assertEqual(len(self.hub.walkthroughs.items[share].buffer.frames), 25)
        return path, share

    def socket(self):
        return self.client.websocket_connect("/api/screen/helper", headers={
            "Authorization": "Bearer " + self.device["token"]})

    def test_transcribe_stop_upload_and_retry(self):
        with self.socket() as ws:
            path, share = self.start(ws, captured=True)
            result = self.client.post("/api/conversations/line/transcribe", content=b"audio")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.client.post(path + "/stop").status_code, 200)
            self.assertEqual(ws.receive_json()["type"], "stop_share")
            payload = {"notes": "notes", "segments": result.json()["segments"], "mark_pointer": True}
            response = self.client.post(path + "/finish", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            message = response.json()["message"]
            self.assertIn("Walkthrough ·", message["body"])
            self.assertIn("click gear", message["body"])
            self.assertIn("view centre; pointer captured", message["body"])
            self.assertNotIn("pointer at -50,50", message["body"])
            self.assertIn("/api/media/", message["body"])
            self.assertGreaterEqual(len(message["files"]), 2)
            self.assertEqual(message["files"][0]["title"], "Walkthrough contact sheet")
            self.assertTrue(all(item["title"] == "Walkthrough frame" for item in message["files"][1:]))
            self.assertLess(message["body"].index("Walkthrough contact sheet"),
                            message["body"].index("Walkthrough frame"))
            self.assertIn("Contact sheet first", message["body"])
            for item in message["files"]:
                self.assertIn(item["id"], message["body"])
                self.assertEqual(self.client.get(item["urls"]["original"]).status_code, 200)
            marked = self.client.get(message["files"][1]["urls"]["original"])
            with Image.open(io.BytesIO(marked.content)) as image:
                self.assertEqual(image.getpixel((image.width // 2, image.height // 2)), (255, 255, 255))
            self.assertNotIn(share, self.hub.walkthroughs.items)
            self.assertEqual(self.client.post(path + "/finish", json=payload).json()["message"]["id"],
                             message["id"])
            self.assertEqual(len(self.db.message_page("line")[0]), 1)

    def test_disconnect_and_recognizer_failure_still_send_frames(self):
        with self.socket() as ws:
            path, share = self.start(ws)
        self.assertNotIn("line", self.hub.shares)
        self.assertTrue(self.hub.walkthroughs.items[share].stopped)
        self.backend.transcribe = lambda *_: (_ for _ in ()).throw(TakeFailed("broken"))
        response = self.client.post("/api/conversations/line/transcribe", content=b"audio")
        self.assertEqual(response.status_code, 422)
        result = self.client.post(path + "/finish", json={"transcription_error": True})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("transcription failed", result.json()["message"]["body"])
        self.assertTrue(result.json()["message"]["files"])

    def test_silent_transcript_sends_frames_without_speech(self):
        self.backend.transcribe = lambda *_: Transcript("", "en", 16, ())
        with self.socket() as ws:
            path, _ = self.start(ws)
            transcript = self.client.post("/api/conversations/line/transcribe", content=b"audio").json()
            self.assertEqual(self.client.post(path + "/stop").status_code, 200)
            self.assertEqual(ws.receive_json()["type"], "stop_share")
            result = self.client.post(path + "/finish", json={"segments": transcript["segments"]})
            self.assertEqual(result.status_code, 200, result.text)
            message = result.json()["message"]
            self.assertTrue(message["files"])
            self.assertIn("→ frame", message["body"])
            self.assertNotIn('""', message["body"])

    def test_no_input_overrides_transcript_and_keeps_media(self):
        with self.socket() as ws:
            path, _ = self.start(ws)
            result = self.client.post(path + "/finish", json={
                "no_input": True, "duration_ms": 31000,
                "segments": [{"start": 0, "end": 1, "text": "imagined speech"}]})
            self.assertEqual(result.status_code, 200, result.text)
            message = result.json()["message"]
            self.assertIn("Walkthrough · 0:31 ·", message["body"])
            self.assertIn("(no speech detected — check the microphone)", message["body"])
            self.assertNotIn("imagined speech", message["body"])
            self.assertTrue(message["files"])

    def finish_untimed(self, text, no_input):
        with self.socket() as ws:
            path, _ = self.start(ws)
            result = self.client.post(path + "/finish", json={
                "transcript_text": text, "no_input": no_input, "duration_ms": 31000})
            self.assertEqual(result.status_code, 200, result.text)
            message = result.json()["message"]
            body = message["body"]
            self.assertIn("Walkthrough · 0:31 ·", body)
            self.assertTrue(message["files"])
            self.assertNotIn(f'[0:00] "{text}"', body)
            return body

    def test_untimed_transcript_keeps_frames_without_inventing_speech_timing(self):
        body = self.finish_untimed("click the gear", False)
        self.assertLess(body.index("click the gear"), body.index("→ frame"))
        self.assertNotIn("no speech detected", body)

    def test_untimed_hallucinated_outro_reads_as_no_speech(self):
        body = self.finish_untimed("Thanks for watching. Bye!", False)
        self.assertNotIn("Thanks for watching. Bye!", body)
        self.assertIn("no speech detected", body)

    def test_untimed_transcript_without_input_reads_as_no_speech(self):
        body = self.finish_untimed("click the gear", True)
        self.assertNotIn("click the gear", body)
        self.assertIn("no speech detected", body)

    def test_store_rejects_mismatched_titles(self):
        with self.assertRaises(ValueError):
            self.store.store("line", 1, [], None, None, titles=["extra"])

    def test_empty_take_has_no_sheet(self):
        with self.socket() as ws:
            path, share = self.start(ws)
            self.hub.walkthroughs.items[share].buffer.clear()
            result = self.client.post(path + "/finish", json={})
            self.assertEqual(result.status_code, 200, result.text)
            message = result.json()["message"]
            self.assertEqual(message["files"], [])
            self.assertNotIn("Contact sheet", message["body"])

    def test_cancel_discards_and_cannot_finish(self):
        with self.socket() as ws:
            path, share = self.start(ws)
            self.assertEqual(self.client.delete(path).status_code, 200)
            self.assertEqual(ws.receive_json()["type"], "stop_share")
            self.assertNotIn(share, self.hub.walkthroughs.items)
            self.assertEqual(self.client.post(path + "/finish", json={}).status_code, 404)
            self.assertFalse(self.db.message_page("line")[0])

    def test_cancel_during_frame_preparation_does_not_persist(self):
        from partyline import walkthrough_routes

        with self.socket() as ws, ThreadPoolExecutor(max_workers=1) as executor:
            path, _ = self.start(ws)
            entered, release = threading.Event(), threading.Event()
            prepare = walkthrough_routes.prepared_file

            def delayed(item):
                entered.set()
                release.wait()
                return prepare(item)

            with patch.object(walkthrough_routes, "prepared_file", side_effect=delayed):
                future = executor.submit(self.client.post, path + "/finish", json={})
                try:
                    entered.wait()
                    self.assertEqual(ws.receive_json()["type"], "stop_share")
                    self.assertEqual(self.client.delete(path).status_code, 200)
                finally:
                    release.set()
                self.assertEqual(future.result().status_code, 409)
            self.assertFalse(self.db.message_page("line")[0])
            self.assertFalse(self.store.list_conversation("line"))

    def test_revoking_device_discards_a_disconnected_take(self):
        with self.socket() as ws:
            path, share = self.start(ws)
        self.assertIn(share, self.hub.walkthroughs.items)
        result = self.client.delete("/api/screen/devices/" + self.device["device_id"])
        self.assertEqual(result.status_code, 200)
        self.assertNotIn(share, self.hub.walkthroughs.items)
        self.assertEqual(self.client.post(path + "/finish", json={}).status_code, 404)
