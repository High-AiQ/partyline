"""Images on a line: storage, limits, serving, and what agents get told.

Every image used here is generated in-process. A fixture PNG checked into the
tree would make these tests a statement about that file rather than about the
code, and a thumbnail test needs a specific size on purpose.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from partyline import auth_store, auth_tokens, media_files as files, media_images as images
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaError, MediaStore, media_root
from partyline.media_routes import media_router
from partyline.runtime import ChatRuntime


def png(width=8, height=8, color=(200, 30, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def gif(width=8, height=8) -> bytes:
    buffer = BytesIO()
    Image.new("P", (width, height)).save(buffer, format="GIF")
    return buffer.getvalue()


def tiff(width=8, height=8) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="TIFF")
    return buffer.getvalue()


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


class MediaRootTest(unittest.TestCase):
    def test_default_root_sits_beside_the_database(self):
        self.assertEqual(
            media_root({}, "/home/someone/.partyline.db"),
            Path("/home/someone/.partyline/media"),
        )

    def test_default_root_is_absolute_even_for_a_relative_database(self):
        root = media_root({}, "scratch.db")
        self.assertTrue(root.is_absolute())
        self.assertEqual(root.name, "media")

    def test_override_replaces_the_root_wholesale(self):
        self.assertEqual(
            media_root({"PARTYLINE_MEDIA_DIR": "~/nas/pics"}, "/db/chat.db"),
            Path(os.path.expanduser("~/nas/pics")),
        )

    def test_blank_override_is_not_an_override(self):
        self.assertEqual(
            media_root({"PARTYLINE_MEDIA_DIR": "   "}, "/db/chat.db"),
            Path("/db/chat/media"),
        )

    def test_one_rule_governs_every_database_path(self):
        # A special case for the default database would silently disagree with
        # the documented rule for every custom one, which is what shipped in an
        # earlier cut of this function and what this test exists to prevent.
        for db_path, expected in (
            ("/tmp/grok.db", "/tmp/grok/media"),
            ("/home/someone/.partyline.db", "/home/someone/.partyline/media"),
            ("/mnt/nas/party/chat.sqlite3", "/mnt/nas/party/chat/media"),
        ):
            with self.subTest(db_path=db_path):
                self.assertEqual(media_root({}, db_path), Path(expected))

    def test_the_repository_artwork_directory_is_refused_as_a_root(self):
        from partyline.media import ARTWORK_DIR

        with self.assertRaises(MediaError):
            media_root({"PARTYLINE_MEDIA_DIR": str(ARTWORK_DIR)}, "/db/chat.db")


class PreparationTest(unittest.TestCase):
    def test_every_image_gets_both_derived_tiers(self):
        # The old contract skipped derivation for a small original, so "the
        # thumbnail" was sometimes the whole file. Nothing is conditional now.
        prepared = images.prepared_image(png(40, 20))
        self.assertEqual((prepared.width, prepared.height), (40, 20))
        for variant in (prepared.thumb, prepared.slim):
            self.assertEqual(Image.open(BytesIO(variant.data)).format, "WEBP")
            self.assertEqual(variant.bytes, len(variant.data))

    def test_a_small_original_is_never_upscaled(self):
        prepared = images.prepared_image(png(40, 20))
        self.assertEqual((prepared.thumb.width, prepared.thumb.height), (40, 20))
        self.assertEqual((prepared.slim.width, prepared.slim.height), (40, 20))

    def test_each_tier_is_reduced_to_its_own_max_edge(self):
        prepared = images.prepared_image(png(images.SLIM_MAX_EDGE + 400, 800))
        self.assertEqual(prepared.thumb.width, images.THUMB_MAX_EDGE)
        self.assertEqual(prepared.slim.width, images.SLIM_MAX_EDGE)
        self.assertLess(prepared.thumb.height, prepared.slim.height)
        # The point of the tier is that it costs less to look at.
        self.assertLess(prepared.thumb.bytes, prepared.slim.bytes)

    def test_palette_image_keeps_its_alpha_channel_in_the_thumbnail(self):
        prepared = images.prepared_image(gif(images.THUMB_MAX_EDGE + 10, 10))
        self.assertIsNotNone(prepared.thumb)

    def test_empty_upload_is_refused(self):
        with self.assertRaises(MediaError) as raised:
            images.prepared_image(b"")
        self.assertEqual(raised.exception.status_code, 400)

    def test_a_file_that_is_not_an_image_is_refused(self):
        with self.assertRaises(MediaError) as raised:
            images.prepared_image(b"#!/bin/sh\nrm -rf /\n")
        self.assertEqual(raised.exception.status_code, 400)

    def test_an_unsupported_image_format_is_refused_by_name(self):
        with self.assertRaises(MediaError) as raised:
            images.prepared_image(tiff())
        self.assertIn("TIFF", raised.exception.detail)

    def test_oversized_bytes_are_refused_with_413(self):
        with self.assertRaises(MediaError) as raised:
            images.prepared_image(b"x" * (images.MAX_IMAGE_BYTES + 1))
        self.assertEqual(raised.exception.status_code, 413)

    def test_a_decompression_bomb_is_refused_before_it_is_decoded(self):
        # Declared enormous, actually tiny: exactly the shape of the attack.
        with mock.patch.object(
            images.Image, "open", return_value=_FakeHugeImage()
        ):
            with self.assertRaises(MediaError) as raised:
                images.prepared_image(png())
        self.assertEqual(raised.exception.status_code, 413)

    def test_an_empty_post_is_refused(self):
        with self.assertRaises(MediaError):
            files.prepared_files([])

    def test_more_files_than_the_cap_are_refused(self):
        with self.assertRaises(MediaError) as raised:
            files.prepared_files(
                [(png(), "image.png", "image/png")] * (files.MAX_FILES_PER_POST + 1)
            )
        self.assertEqual(raised.exception.status_code, 400)


class _FakeHugeImage:
    width = 100_000
    height = 100_000
    format = "PNG"
    mode = "RGB"

    def load(self):  # pragma: no cover - the size check refuses before this
        raise AssertionError("a bomb must be refused before it is decoded")


class MetadataTest(unittest.TestCase):
    def test_blank_metadata_becomes_null(self):
        self.assertEqual(images.validated_metadata("  ", None), (None, None))

    def test_metadata_is_trimmed(self):
        self.assertEqual(images.validated_metadata(" hi ", " there "), ("hi", "there"))

    def test_an_oversized_title_is_refused(self):
        with self.assertRaises(MediaError) as raised:
            images.validated_metadata("t" * (images.MAX_TITLE + 1), None)
        self.assertIn("title", raised.exception.detail)

    def test_an_oversized_description_is_refused(self):
        with self.assertRaises(MediaError) as raised:
            images.validated_metadata(None, "d" * (images.MAX_DESCRIPTION + 1))
        self.assertIn("description", raised.exception.detail)


class ImageApiTest(unittest.TestCase):
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
        # Every request is authenticated as the human "opus" unless a test
        # overrides the header with a machine token or clears it.
        self.client.headers["Authorization"] = f"Bearer {access}"

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def machine_headers(self, att_id):
        token = auth_store.ensure_api_token(self.db, att_id)
        return {"Authorization": f"Bearer {token}"}

    def post(self, files=None, headers=None, **fields):
        return self.client.post(
            "/api/conversations/line/images",
            data=fields,
            files=files if files is not None else [("file", ("a.png", png(), "image/png"))],
            headers=headers,
        )

    def test_upload_posts_a_message_carrying_the_image(self):
        response = self.post(title="A chart", description="revenue by quarter", body="look")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        image = payload["files"][0]
        self.assertEqual(image["title"], "A chart")
        self.assertEqual(image["mime"], "image/png")
        self.assertEqual(image["thumb"]["mime"], "image/webp")
        self.assertEqual(image["slim"]["mime"], "image/webp")
        self.assertGreater(image["thumb"]["bytes"], 0)
        self.assertTrue(image["urls"]["original"].startswith("http://"))
        self.assertEqual(payload["message"]["sender_type"], "human")
        self.assertEqual(payload["message"]["files"][0]["id"], image["id"])

    def test_the_stored_body_tells_an_agent_what_the_picture_is(self):
        self.post(title="A chart", description="revenue by quarter", body="look")
        body = self.db.list_messages("line")[-1]["body"]
        caption, metadata = body.split("\n")
        self.assertEqual(caption, "look")
        self.assertTrue(metadata.startswith("📷 A chart — revenue by quarter · 8×8 · thumb: http"))

    def test_metadata_lines_are_a_trailing_run_in_image_order(self):
        self.post(files=[
            ("file", ("a.png", png(4, 4), "image/png")),
            ("file", ("b.png", png(6, 6), "image/png")),
        ], body="two")
        lines = self.db.list_messages("line")[-1]["body"].split("\n")
        self.assertEqual(lines[0], "two")
        self.assertIn("4×4", lines[1])
        self.assertIn("6×6", lines[2])

    def test_an_untitled_image_still_gets_a_readable_line(self):
        self.post()
        self.assertTrue(self.db.list_messages("line")[-1]["body"].startswith("📷 image · 8×8"))

    def test_the_broadcast_event_carries_relative_urls(self):
        response = self.post()
        image = self.socket.events[-1]["message"]["files"][0]
        self.assertEqual(image["urls"]["original"], f"/api/media/{image['id']}/original")
        self.assertEqual(self.socket.events[-1]["type"], "message")
        self.assertEqual(response.json()["files"][0]["id"], image["id"])

    def test_a_mention_wakes_a_process_with_the_image_metadata(self):
        self.db.add_attachment("att", "line", "kimi", "fake", ["fake"], "/tmp", "owner")
        self.db.set_attachment_status("att", "running", "owner")
        adapter = RecordingAdapter({"runtime_owner": "owner"})
        self.runtime.live["att"] = adapter
        self.post(title="Trace", body="@kimi what is this")
        delivered = adapter.deliveries[0][-1]["body"]
        self.assertIn("📷 Trace", delivered)

    def test_a_machine_credential_posts_as_an_agent_under_its_own_name(self):
        self.db.add_attachment("att", "line", "kimi", "fake", ["fake"], "/tmp", "owner")
        self.db.set_attachment_status("att", "running", "owner")
        message = self.post(headers=self.machine_headers("att")).json()["message"]
        self.assertEqual(message["sender_type"], "agent")
        self.assertEqual(message["sender"], "kimi")

    def test_a_large_image_gets_a_thumbnail_of_its_own(self):
        response = self.post(files=[("file", ("big.png", png(2000, 1000), "image/png"))])
        image = response.json()["files"][0]
        self.assertEqual(image["thumb"]["mime"], "image/webp")
        self.assertEqual(image["thumb"]["width"], images.THUMB_MAX_EDGE)
        served = self.client.get(f"/api/media/{image['id']}/thumb")
        self.assertEqual(served.headers["content-type"], "image/webp")
        self.assertEqual(Image.open(BytesIO(served.content)).width, images.THUMB_MAX_EDGE)

    def test_every_tier_is_served_as_its_own_file(self):
        image = self.post().json()["files"][0]
        served = {
            tier: self.client.get(f"/api/media/{image['id']}/{tier}")
            for tier in ("original", "thumb", "slim")
        }
        self.assertEqual(served["original"].headers["content-type"], "image/png")
        for tier in ("thumb", "slim"):
            self.assertEqual(served[tier].headers["content-type"], "image/webp")
            self.assertNotEqual(served[tier].content, served["original"].content)
            self.assertIn("immutable", served[tier].headers["cache-control"])

    def test_the_derived_files_are_named_for_their_tier(self):
        image = self.post().json()["files"][0]
        names = sorted(path.name for path in (self.root / "line").iterdir())
        self.assertEqual(names, sorted([
            f"{image['id']}.png", f"{image['id']}_slim.webp", f"{image['id']}_thumb.webp",
        ]))

    def test_the_digest_line_offers_all_three_tiers(self):
        self.post(title="A chart")
        line = self.db.list_messages("line")[-1]["body"].splitlines()[-1]
        image = self.client.get("/api/conversations/line/images").json()[0]
        self.assertEqual(
            line,
            f"📷 A chart · 8×8"
            f" · thumb: {image['urls']['thumb']}"
            f" · slim: {image['urls']['slim']}"
            f" · original: {image['urls']['original']}",
        )

    def test_six_images_are_allowed_and_seven_are_not(self):
        six = [("file", (f"{n}.png", png(), "image/png")) for n in range(6)]
        self.assertEqual(len(self.post(files=six).json()["files"]), 6)
        self.assertEqual(self.post(files=six + six[:1]).status_code, 400)

    def test_a_refused_upload_leaves_no_message_behind(self):
        before = len(self.db.list_messages("line"))
        self.assertEqual(self.post(files=[("file", ("empty", b"", None))]).status_code, 400)
        self.assertEqual(len(self.db.list_messages("line")), before)

    def test_one_empty_file_refuses_the_whole_post(self):
        self.assertEqual(
            self.post(files=[
                ("file", ("a.png", png(), "image/png")),
                ("file", ("b.png", b"", "image/png")),
            ]).status_code,
            400,
        )
        self.assertEqual(self.db.list_messages("line"), [])

    def test_an_oversized_upload_is_refused_with_413(self):
        with mock.patch.object(files, "MAX_FILE_BYTES", 2):
            response = self.post(files=[("file", ("big.txt", b"xxx", "text/plain"))])
        self.assertEqual(response.status_code, 413)

    def test_an_unauthenticated_upload_is_401(self):
        response = self.post(headers={"Authorization": ""})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.db.list_messages("line"), [])

    def test_an_oversized_title_is_refused(self):
        self.assertEqual(self.post(title="t" * 400).status_code, 400)

    def test_an_unknown_line_is_a_404(self):
        response = self.client.post(
            "/api/conversations/nope/images",
            files=[("file", ("a.png", png(), "image/png"))],
        )
        self.assertEqual(response.status_code, 404)

    def test_an_archived_line_refuses_uploads(self):
        self.db.archive_conversation("line")
        self.assertEqual(self.post().status_code, 409)

    def test_listing_a_line_returns_its_images_with_absolute_urls(self):
        self.post(title="one")
        self.post(title="two")
        listed = self.client.get("/api/conversations/line/images").json()
        self.assertEqual([image["title"] for image in listed], ["one", "two"])
        self.assertTrue(listed[0]["urls"]["thumb"].startswith("http://"))

    def test_listing_an_unknown_line_is_a_404(self):
        self.assertEqual(self.client.get("/api/conversations/nope/images").status_code, 404)

    def test_an_unknown_image_or_variant_is_a_404(self):
        image = self.post().json()["files"][0]
        self.assertEqual(self.client.get("/api/media/missing/original").status_code, 404)
        self.assertEqual(self.client.get(f"/api/media/{image['id']}/raw").status_code, 404)

    def test_a_row_whose_file_has_vanished_is_a_404_not_a_traceback(self):
        image = self.post().json()["files"][0]
        for path in (self.root / "line").iterdir():
            path.unlink()
        self.assertEqual(self.client.get(f"/api/media/{image['id']}/original").status_code, 404)

    def test_images_are_segregated_by_line(self):
        self.db.create_conversation("other", "Other")
        self.post()
        self.assertTrue((self.root / "line").is_dir())
        self.assertFalse((self.root / "other").exists())

    def test_stored_paths_are_relative_so_the_root_can_move(self):
        image = self.post().json()["files"][0]
        stored = self.db.conn.execute(
            "SELECT path FROM images WHERE id=?", (image["id"],)
        ).fetchone()["path"]
        self.assertFalse(stored.startswith("/"))
        moved = Path(self.directory.name) / "moved"
        self.root.rename(moved)
        relocated = MediaStore(self.db, moved)
        self.assertIsNotNone(relocated.file_for(image["id"], "original"))

    def test_a_line_id_cannot_escape_the_media_root(self):
        with self.assertRaises(MediaError):
            self.store.delete_conversation("../../etc")

    def test_purging_a_line_destroys_its_pictures(self):
        image = self.post().json()["files"][0]
        self.store.delete_conversation("line")
        self.assertFalse((self.root / "line").exists())
        self.assertIsNone(self.store.file_for(image["id"], "original"))

    def test_attach_hangs_images_off_the_messages_that_carry_them(self):
        self.post(title="one")
        self.db.add_message("line", "greg", "human", "no picture here")
        attached = self.store.attach(self.db.list_messages("line"))
        self.assertEqual(attached[0]["files"][0].title, "one")
        self.assertEqual(attached[-1]["files"], [])

    def test_a_failed_write_leaves_no_orphan_bytes_on_disk(self):
        # Files with no row pointing at them are invisible to every query here,
        # so nothing would ever clean them up. Prove the rollback, don't assume it.
        prepared = files.prepared_files([(png(), "image.png", "image/png")])
        with mock.patch("partyline.media.INSERT", "INSERT INTO no_such_table VALUES(1)"):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.store("line", 1, prepared, None, None)
        self.assertEqual(list((self.root / "line").iterdir()), [])

    def test_a_failed_store_takes_its_message_row_with_it(self):
        with mock.patch.object(
            MediaStore, "store", side_effect=RuntimeError("disk went away")
        ):
            with self.assertRaises(RuntimeError):
                self.post()
        self.assertEqual(self.db.list_messages("line"), [])

    def test_a_variant_of_unknown_size_reports_unknown_not_free(self):
        """A row derived before sizes were recorded must not price itself at 0.

        Zero reads as "free to fetch", which is the one question the field
        exists to answer — a false price is worse than a missing one.
        """
        image = self.post().json()["files"][0]
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE images SET thumb_bytes=NULL WHERE id=?", (image["id"],)
            )
            self.db.conn.commit()
        legacy = self.store.for_message(self.db.list_messages("line")[-1]["id"])[0]
        self.assertIsNone(legacy.thumb.bytes)
        self.assertEqual(legacy.thumb.mime, "image/webp")
        self.assertEqual(
            self.client.get(f"/api/media/{image['id']}/thumb").status_code, 200
        )

    def test_attach_of_nothing_is_nothing(self):
        self.assertEqual(self.store.attach([]), [])


class DotenvOrderingTest(unittest.TestCase):
    """A .env-only media directory must win, and the proof cannot be faked.

    ``runtime``, ``media``, and the router all bind at import, so this is a
    question about import order that an in-process test cannot honestly ask —
    the module is already imported by then. Each case runs a fresh interpreter
    in a directory holding a real .env and reports where the store landed.
    """

    def resolved_root(self, directory: str, dotenv: str | None) -> str:
        if dotenv is not None:
            Path(directory, ".env").write_text(dotenv, encoding="utf-8")
        finished = subprocess.run(
            [sys.executable, "-c", "import partyline.server as s; print(s.media.root)"],
            cwd=directory,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PARTYLINE_DB": f"{directory}/chat.db",
                "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            },
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        return finished.stdout.strip()

    def test_a_dotenv_media_directory_is_honoured(self):
        # The failing control for grok's QA finding: before .env was merged
        # ahead of the import-time bindings, this returned <db>/media and the
        # configured NAS path was silently ignored.
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                self.resolved_root(directory, f"PARTYLINE_MEDIA_DIR={directory}/nas\n"),
                f"{directory}/nas",
            )

    def test_without_a_dotenv_the_root_still_follows_the_database(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.resolved_root(directory, None), f"{directory}/chat/media")


class ServerWiringTest(unittest.TestCase):
    """The routes are only useful if the server actually mounted them."""

    def test_the_media_routes_are_mounted_on_the_app(self):
        from partyline import server

        # Ask the schema the app publishes, not `app.routes`: an included
        # router is a nested object there, so walking that list reports a
        # mounted route as missing — a false negative that looked like a real
        # wiring bug for a while.
        paths = set(server.app.openapi()["paths"])
        self.assertIn("/api/conversations/{conv_id}/images", paths)
        self.assertIn("/api/media/{file_id}/{variant}", paths)

    def test_conversation_detail_carries_images(self):
        import asyncio

        from partyline import server

        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            store = MediaStore(db, Path(directory) / "media")
            original_runtime, original_media = server.runtime, server.media
            server.runtime, server.media = ChatRuntime(db), store
            try:
                db.create_conversation("line", "Line")
                message = db.add_message("line", "opus", "agent", "look")
                store.store(
                    "line",
                    message["id"],
                    files.prepared_files([(png(), "image.png", "image/png")]),
                    "T",
                    None,
                )
                detail = asyncio.run(server.conversation_detail("line"))
                self.assertEqual(detail["messages"][0]["files"][0].title, "T")
                with self.assertRaises(HTTPException):
                    asyncio.run(server.conversation_detail("missing"))
            finally:
                server.runtime, server.media = original_runtime, original_media
                db.close()


if __name__ == "__main__":
    unittest.main()
