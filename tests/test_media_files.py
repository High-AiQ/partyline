"""Unit coverage for arbitrary-file classification and storage."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

from partyline.db import Db
from partyline.media import MediaStore
from partyline import media_files as files


def image_bytes(format_: str = "PNG") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (7, 5), (20, 40, 60)).save(buffer, format=format_)
    return buffer.getvalue()


class FilePreparationTest(unittest.TestCase):
    def test_bytes_not_the_filename_or_declared_mime_decide_an_image(self):
        prepared = files.prepared_file(
            (image_bytes(), "report.pdf", "application/pdf")
        )
        self.assertEqual(prepared.kind, "image")
        self.assertEqual(prepared.mime, "image/png")
        self.assertEqual(prepared.ext, "png")
        self.assertEqual(prepared.filename, "report.pdf")
        self.assertEqual((prepared.width, prepared.height), (7, 5))
        self.assertIsNotNone(prepared.thumb)

    def test_svg_is_a_file_even_though_its_mime_starts_with_image(self):
        prepared = files.prepared_file(
            (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "shape.svg", "image/png")
        )
        self.assertEqual(prepared.kind, "file")
        self.assertEqual(prepared.mime, "image/svg+xml")
        self.assertIsNone(prepared.width)

    def test_audio_and_video_kinds_come_from_resolved_mime(self):
        cases = (
            ((b"wav", "sound.wav", "text/plain"), "audio", "audio/x-wav"),
            ((b"mp4", None, "video/mp4; charset=binary"), "video", "video/mp4"),
        )
        for upload, kind, mime in cases:
            with self.subTest(kind=kind):
                prepared = files.prepared_file(upload)
                self.assertEqual((prepared.kind, prepared.mime), (kind, mime))

    def test_declared_image_mime_does_not_make_opaque_bytes_an_image(self):
        prepared = files.prepared_file((b"not png", "fake.png", "image/png"))
        self.assertEqual(prepared.kind, "file")
        self.assertEqual(prepared.mime, "image/png")

    def test_unknown_type_and_missing_filename_get_safe_defaults(self):
        prepared = files.prepared_file((b"opaque", None, None))
        self.assertEqual(prepared.kind, "file")
        self.assertEqual(prepared.mime, "application/octet-stream")
        self.assertEqual(prepared.ext, "bin")
        self.assertIsNone(prepared.filename)

    def test_invalid_declared_mime_is_ignored(self):
        prepared = files.prepared_file((b"opaque", None, "not a mime"))
        self.assertEqual(prepared.mime, "application/octet-stream")

    def test_mime_supplies_extension_when_the_filename_cannot(self):
        prepared = files.prepared_file((b"plain", "odd.$$$", "text/plain"))
        self.assertEqual(prepared.ext, "txt")

    def test_paths_and_control_characters_are_removed_from_filename(self):
        prepared = files.prepared_file((b"hello", "../dir\\bad\nname.txt", None))
        self.assertEqual(prepared.filename, "badname.txt")

    def test_dot_names_become_an_absent_filename(self):
        self.assertIsNone(files.prepared_file((b"x", "..", None)).filename)

    def test_empty_file_and_empty_post_are_refused(self):
        for call in (
            lambda: files.prepared_file((b"", "empty.txt", "text/plain")),
            lambda: files.prepared_files([]),
        ):
            with self.assertRaises(files.MediaError) as raised:
                call()
            self.assertEqual(raised.exception.status_code, 400)

    def test_post_count_and_non_image_byte_limits_are_enforced(self):
        upload = (b"x", "x.txt", "text/plain")
        with self.assertRaises(files.MediaError):
            files.prepared_files([upload] * (files.MAX_FILES_PER_POST + 1))
        with mock.patch.object(files, "MAX_FILE_BYTES", 2):
            with self.assertRaises(files.MediaError) as raised:
                files.prepared_file((b"xxx", "x.txt", "text/plain"))
        self.assertEqual(raised.exception.status_code, 413)

    def test_supported_image_cannot_evade_the_smaller_image_limit(self):
        with mock.patch("partyline.media_images.MAX_IMAGE_BYTES", 2):
            with self.assertRaises(files.MediaError) as raised:
                files.prepared_file((image_bytes(), "actually.pdf", "application/pdf"))
        self.assertEqual(raised.exception.status_code, 413)
        self.assertIn("image", raised.exception.detail)

    def test_corrupt_supported_image_bytes_fall_back_to_a_file(self):
        damaged = image_bytes()[:55]
        prepared = files.prepared_file((damaged, "broken.png", "image/png"))
        self.assertEqual(prepared.kind, "file")

    def test_pillow_format_outside_the_supported_set_is_a_file(self):
        prepared = files.prepared_file((image_bytes("TIFF"), "scan.tiff", None))
        self.assertEqual(prepared.kind, "file")
        self.assertEqual(prepared.mime, "image/tiff")

    def test_size_formatting_is_human_readable(self):
        self.assertEqual(files.formatted_size(0), "0 B")
        self.assertEqual(files.formatted_size(999), "999 B")
        self.assertEqual(files.formatted_size(1500), "1.5 KB")
        self.assertEqual(files.formatted_size(2_000_000), "2.0 MB")
        self.assertEqual(files.formatted_size(2_000_000_000), "2.0 GB")


class FileStorageTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/chat.db")
        self.root = Path(self.directory.name) / "media"
        self.store = MediaStore(self.db, self.root)

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_non_image_stores_only_original_and_maps_zero_dimensions_to_none(self):
        prepared = files.prepared_files([(b"hello", "notes.txt", "text/plain")])
        ref = self.store.store("line", 1, prepared, None, None)[0]
        self.assertEqual(ref.kind, "file")
        self.assertEqual(ref.filename, "notes.txt")
        self.assertIsNone(ref.width)
        self.assertIsNone(ref.height)
        self.assertIsNone(ref.thumb)
        self.assertIsNone(ref.slim)
        self.assertEqual(len(list((self.root / "line").iterdir())), 1)
        for variant in ("original", "thumb", "slim"):
            located = self.store.file_for(ref.id, variant)
            self.assertIsNotNone(located)
            self.assertEqual(located[0].read_bytes(), b"hello")
            self.assertEqual(located[2], "notes.txt")

    def test_pre_existing_null_kind_row_is_still_an_image(self):
        prepared = files.prepared_files([(image_bytes(), "old.png", "image/png")])
        ref = self.store.store("line", 1, prepared, None, None)[0]
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE images SET kind=NULL, filename=NULL, slim_path=NULL WHERE id=?",
                (ref.id,),
            )
            self.db.conn.commit()
        legacy = self.store.for_message(1)[0]
        self.assertEqual(legacy.kind, "image")
        self.assertIsNone(legacy.filename)
        self.assertEqual((legacy.width, legacy.height), (7, 5))
        self.assertIsNotNone(legacy.thumb)
        self.assertIsNone(legacy.slim)

    def test_null_kind_with_zero_dimensions_cannot_emit_a_zero_by_zero_image(self):
        prepared = files.prepared_files([(b"hello", "notes.txt", "text/plain")])
        ref = self.store.store("line", 1, prepared, None, None)[0]
        with self.db.lock:
            self.db.conn.execute("UPDATE images SET kind=NULL WHERE id=?", (ref.id,))
            self.db.conn.commit()
        recovered = self.store.for_message(1)[0]
        self.assertEqual(recovered.kind, "file")
        self.assertIsNone(recovered.width)
        self.assertIsNone(recovered.height)

    def test_message_attachment_uses_the_files_wire_field(self):
        message = {"id": 1, "body": "read this"}
        prepared = files.prepared_files([(b"hello", "notes.txt", "text/plain")])
        self.store.store("line", 1, prepared, None, None)
        attached = self.store.attach([message])[0]
        self.assertNotIn("images", attached)
        self.assertEqual(attached["files"][0].filename, "notes.txt")


if __name__ == "__main__":
    unittest.main()
