"""Route-level coverage for posting any file type.

Kind resolution and storage live in the media modules; this file asks the HTTP
surface: canonical vs alias paths, digest lines, serving headers, and the
non-image size cap. Fixtures are tiny in-process bytes — no files on disk.
"""

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from partyline import auth_store, auth_tokens
from partyline.adapters.briefing import BRIEFING
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.media_files import MAX_FILE_BYTES
from partyline.media_routes import media_router
from partyline.runtime import ChatRuntime
from partyline.server import app as server_app


class CollectingSocket:
    """Stand-in for a browser: keeps every event the runtime broadcasts."""

    def __init__(self):
        self.events = []

    async def send_json(self, payload):
        self.events.append(payload)


class RecordingAdapter:
    """A live attachment that records the digests delivered to its pty."""

    def __init__(self, att):
        self.att = att
        self.deliveries = []

    async def deliver(self, messages):
        self.deliveries.append(messages)


def png(width=8, height=8) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def pdf() -> bytes:
    return b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def wav() -> bytes:
    # 44-byte header + a few samples; mime comes from the filename, not decode.
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 28


def mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16


def txt() -> bytes:
    return b"hello from the line\n"


def html() -> bytes:
    return b"<!doctype html><html><body>hi</body></html>"


def svg() -> bytes:
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'


def xhtml() -> bytes:
    return b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><script/></html>'


class FileRoutesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.root = Path(self.directory.name) / "media"
        self.store = MediaStore(self.db, self.root)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(media_router(self.runtime, self.store))
        self.client = TestClient(app)
        self.db.create_conversation("line", "Line")
        self.socket = CollectingSocket()
        self.runtime.sockets["line"] = {self.socket}
        user = auth_store.create_user(
            self.db, "opus@example.com", "opus", auth_tokens.hash_password("hunter2222"))
        access = auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])
        self.client.headers["Authorization"] = f"Bearer {access}"

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def post(self, path="/api/conversations/line/files", files=None, **fields):
        return self.client.post(
            path,
            data=fields,
            files=files if files is not None else [("file", ("a.png", png(), "image/png"))],
        )

    def test_briefing_teaches_any_file_type_and_how_to_read_a_pdf(self):
        self.assertIn("$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/files", BRIEFING)
        self.assertIn("$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/images", BRIEFING)
        self.assertIn("PDF", BRIEFING)
        self.assertIn("GET the `original`", BRIEFING)
        self.assertIn('Authorization: Bearer $PARTYLINE_TOKEN', BRIEFING)

    def test_briefing_formats_cleanly_despite_table_syntax(self):
        """The attach-time .format() must never trip on a stray brace."""
        from partyline.adapters.briefing import TOPIC_BRIEFING

        text = BRIEFING.format(name="probe", conv="line")
        self.assertIn('"probe"', text)
        self.assertIn('"line"', text)
        self.assertIn("station", TOPIC_BRIEFING.format(topic="station"))

    def test_the_canonical_and_alias_upload_paths_are_mounted(self):
        spec = server_app.openapi()
        paths = set(spec["paths"])
        self.assertIn("/api/conversations/{conv_id}/files", paths)
        self.assertIn("/api/conversations/{conv_id}/images", paths)
        self.assertIn("/api/media/{file_id}/{variant}", paths)
        operation_ids = [
            method["operationId"]
            for item in spec["paths"].values()
            for method in item.values()
            if "operationId" in method
        ]
        self.assertEqual(len(operation_ids), len(set(operation_ids)), operation_ids)

    def test_a_pdf_is_kind_file_with_an_attachment_digest(self):
        response = self.post(files=[("file", ("notes.pdf", pdf(), "application/pdf"))])
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        ref = payload["files"][0]
        self.assertEqual(ref["kind"], "file")
        self.assertEqual(ref["filename"], "notes.pdf")
        self.assertEqual(ref["mime"], "application/pdf")
        self.assertIsNone(ref["width"])
        self.assertIsNone(ref["height"])
        self.assertTrue(ref["urls"]["original"].endswith(f"/api/media/{ref['id']}/original"))
        self.assertEqual(ref["urls"]["thumb"], ref["urls"]["original"].replace(
            "/original", "/thumb"))
        line = self.db.list_messages("line")[-1]["body"].splitlines()[-1]
        self.assertTrue(line.startswith("📎 notes.pdf · application/pdf · "), line)
        self.assertIn(f"/api/media/{ref['id']}/original", line)
        self.assertNotIn("thumb:", line)
        self.assertEqual(payload["message"]["files"][0]["id"], ref["id"])

    def test_a_wav_is_kind_audio(self):
        ref = self.post(files=[("file", ("clip.wav", wav(), "audio/wav"))]).json()["files"][0]
        self.assertEqual(ref["kind"], "audio")
        self.assertTrue(ref["mime"].startswith("audio/"))
        line = self.db.list_messages("line")[-1]["body"]
        self.assertTrue(line.startswith("🎵 clip.wav · "), line)
        self.assertIn(f"/api/media/{ref['id']}/original", line)

    def test_an_mp4_is_kind_video(self):
        ref = self.post(files=[("file", ("clip.mp4", mp4(), "video/mp4"))]).json()["files"][0]
        self.assertEqual(ref["kind"], "video")
        self.assertTrue(ref["mime"].startswith("video/"))
        line = self.db.list_messages("line")[-1]["body"]
        self.assertTrue(line.startswith("🎬 clip.mp4 · "), line)
        self.assertIn(f"/api/media/{ref['id']}/original", line)

    def test_a_txt_is_kind_file(self):
        ref = self.post(files=[("file", ("notes.txt", txt(), "text/plain"))]).json()["files"][0]
        self.assertEqual(ref["kind"], "file")
        self.assertEqual(ref["mime"], "text/plain")
        line = self.db.list_messages("line")[-1]["body"]
        self.assertTrue(line.startswith("📎 notes.txt · text/plain · "), line)

    def test_filename_wins_the_digest_label_and_description_still_appends(self):
        self.post(
            files=[("file", ("notes.pdf", pdf(), "application/pdf"))],
            title="ignored-when-named",
            description="board packet",
        )
        line = self.db.list_messages("line")[-1]["body"]
        self.assertTrue(line.startswith("📎 notes.pdf — board packet · application/pdf · "), line)

    def test_an_image_posted_to_files_keeps_tiers_and_the_camera_digest(self):
        payload = self.post(files=[("file", ("chart.png", png(), "image/png"))]).json()
        ref = payload["files"][0]
        self.assertEqual(ref["kind"], "image")
        self.assertEqual(ref["width"], 8)
        self.assertEqual(ref["height"], 8)
        self.assertIsNotNone(ref["thumb"])
        self.assertIsNotNone(ref["slim"])
        line = self.db.list_messages("line")[-1]["body"]
        # Image digest labels stay title-first (untitled → "image") so existing
        # agent readers keep working; the filename still rides on the FileRef.
        self.assertEqual(ref["filename"], "chart.png")
        self.assertTrue(line.startswith("📷 image · 8×8 · thumb: "), line)
        self.assertIn(" · slim: ", line)
        self.assertIn(" · original: ", line)

    def test_the_images_alias_posts_and_lists_the_same_as_files(self):
        uploaded = self.post(
            "/api/conversations/line/images",
            files=[("file", ("notes.pdf", pdf(), "application/pdf"))],
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()["files"][0]["kind"], "file")
        via_files = self.client.get("/api/conversations/line/files").json()
        via_images = self.client.get("/api/conversations/line/images").json()
        self.assertEqual(via_files, via_images)
        self.assertEqual(via_files[0]["id"], uploaded.json()["files"][0]["id"])
        self.assertTrue(via_files[0]["urls"]["original"].startswith("http://"))

    def test_listing_an_unknown_line_is_a_404_on_both_paths(self):
        self.assertEqual(self.client.get("/api/conversations/nope/files").status_code, 404)
        self.assertEqual(self.client.get("/api/conversations/nope/images").status_code, 404)

    def test_every_media_response_is_nosniff(self):
        ref = self.post(files=[("file", ("notes.pdf", pdf(), "application/pdf"))]).json()["files"][0]
        for variant in ("original", "thumb", "slim"):
            served = self.client.get(f"/api/media/{ref['id']}/{variant}")
            self.assertEqual(served.status_code, 200)
            self.assertEqual(served.headers["x-content-type-options"], "nosniff")
            self.assertIn("immutable", served.headers["cache-control"])
            disposition = served.headers["content-disposition"]
            self.assertTrue(disposition.startswith("inline;"), disposition)
            self.assertIn("notes.pdf", disposition)

    def test_html_is_forced_to_download(self):
        ref = self.post(
            files=[("file", ("page.html", html(), "text/html"))],
        ).json()["files"][0]
        self.assertEqual(ref["kind"], "file")
        served = self.client.get(f"/api/media/{ref['id']}/original")
        self.assertEqual(served.headers["x-content-type-options"], "nosniff")
        self.assertTrue(served.headers["content-disposition"].startswith("attachment;"))
        self.assertIn("page.html", served.headers["content-disposition"])

    def test_svg_is_kind_file_and_forced_to_download(self):
        ref = self.post(
            files=[("file", ("icon.svg", svg(), "image/svg+xml"))],
        ).json()["files"][0]
        self.assertEqual(ref["kind"], "file")
        served = self.client.get(f"/api/media/{ref['id']}/original")
        self.assertTrue(served.headers["content-disposition"].startswith("attachment;"))
        self.assertIn("icon.svg", served.headers["content-disposition"])

    def test_xhtml_is_forced_to_download(self):
        ref = self.post(
            files=[("file", ("page.xhtml", xhtml(), "application/xhtml+xml"))],
        ).json()["files"][0]
        self.assertEqual(ref["kind"], "file")
        self.assertEqual(ref["mime"], "application/xhtml+xml")
        served = self.client.get(f"/api/media/{ref['id']}/original")
        self.assertTrue(served.headers["content-disposition"].startswith("attachment;"))
        self.assertIn("page.xhtml", served.headers["content-disposition"])

    def test_disposition_allowlist_for_svg_xhtml_pdf_wav_and_zip(self):
        cases = (
            ("icon.svg", svg(), "image/svg+xml", "attachment"),
            ("page.xhtml", xhtml(), "application/xhtml+xml", "attachment"),
            ("notes.pdf", pdf(), "application/pdf", "inline"),
            ("clip.wav", wav(), "audio/wav", "inline"),
            ("blob.zip", b"PK\x03\x04", "application/zip", "attachment"),
        )
        for name, data, mime, expected in cases:
            with self.subTest(name=name):
                ref = self.post(files=[("file", (name, data, mime))]).json()["files"][0]
                served = self.client.get(f"/api/media/{ref['id']}/original")
                self.assertTrue(
                    served.headers["content-disposition"].startswith(f"{expected};"),
                    served.headers["content-disposition"],
                )

    def test_a_file_over_the_non_image_cap_is_refused_with_413(self):
        self.assertEqual(MAX_FILE_BYTES, 100 * 1024 * 1024)
        # Patch the cap rather than allocate 100 MB: the refusal path is the
        # same, and a hung allocating test has taken this machine down before.
        with mock.patch("partyline.media_files.MAX_FILE_BYTES", 2):
            self.assertEqual(
                self.post(
                    files=[("file", ("big.bin", b"xxx", "application/octet-stream"))]
                ).status_code,
                413,
            )
        self.assertEqual(self.db.list_messages("line"), [])

    def test_a_mention_wakes_a_process_with_the_file_digest(self):
        self.db.add_attachment("att", "line", "kimi", "fake", ["fake"], "/tmp", "owner")
        self.db.set_attachment_status("att", "running", "owner")
        adapter = RecordingAdapter({"runtime_owner": "owner"})
        self.runtime.live["att"] = adapter
        self.post(
            files=[("file", ("notes.pdf", pdf(), "application/pdf"))],
            body="@kimi read this",
        )
        delivered = adapter.deliveries[0][-1]["body"]
        self.assertIn("@kimi read this", delivered)
        self.assertIn("📎 notes.pdf", delivered)

    def test_the_broadcast_event_carries_files_not_images(self):
        self.post(files=[("file", ("notes.txt", txt(), "text/plain"))])
        event = self.socket.events[-1]
        self.assertEqual(event["type"], "message")
        self.assertIn("files", event["message"])
        self.assertNotIn("images", event["message"])
        self.assertEqual(event["message"]["files"][0]["kind"], "file")
        self.assertEqual(
            event["message"]["files"][0]["urls"]["original"],
            f"/api/media/{event['message']['files'][0]['id']}/original",
        )


if __name__ == "__main__":
    unittest.main()
