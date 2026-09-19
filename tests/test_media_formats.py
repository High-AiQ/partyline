"""Uploads in formats agents cannot natively decode: kept, labelled, readable.

Every fixture is generated in-process when a decoder exists, and the test
says so when it does not — a checked-in binary would make these tests a
statement about that file rather than about the pipeline.
"""

from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from PIL import Image, features

from partyline.db import Db
from partyline import media_digest as digest
from partyline import media_formats as formats
from partyline import media_images as images
from partyline.media import MediaStore


def avif_bytes(width=40, height=20) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (9, 99, 9)).save(buffer, format="AVIF")
    return buffer.getvalue()


def bmp_bytes(width=40, height=20) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (9, 9, 99)).save(buffer, format="BMP")
    return buffer.getvalue()


def static_webp_bytes(width=40, height=20) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (99, 9, 99)).save(buffer, format="WEBP")
    return buffer.getvalue()


def animated_webp_bytes(width=40, height=20) -> bytes:
    frames = [
        Image.new("RGB", (width, height), color) for color in ((200, 0, 0), (0, 200, 0))
    ]
    buffer = BytesIO()
    frames[0].save(
        buffer, format="WEBP", save_all=True, append_images=frames[1:], duration=100
    )
    return buffer.getvalue()


def heic_signature_bytes() -> bytes:
    """A valid ``ftyp`` brand and nothing else: exactly what a browser sends."""
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 8


HAS_AVIF = features.check("avif")


class SignatureTest(unittest.TestCase):
    def test_magic_bytes_name_the_format(self):
        for data, expected in (
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "PNG"),
            (b"\xff\xd8\xff" + b"\x00" * 8, "JPEG"),
            (b"GIF89a" + b"\x00" * 8, "GIF"),
            (b"RIFF\x00\x00\x00\x00WEBP", "WEBP"),
            (b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00avifmif1", "AVIF"),
            (b"\x00\x00\x00\x20ftypavis\x00\x00\x00\x00avis", "AVIF"),
            (b"\x00\x00\x00\x20ftypheic\x00\x00\x00\x00heicmif1", "HEIC"),
            (b"\x00\x00\x00\x20ftypmif1\x00\x00\x00\x00mif1heic", "HEIF"),
            (b"\xff\x0a" + b"\x00" * 8, "JXL"),
            (b"\x00\x00\x00\x0cJXL \r\n\x87\n", "JXL"),
            (b"BM\x00\x00\x00\x00" + b"\x00" * 8, "BMP"),
            (b"II*\x00" + b"\x00" * 8, "TIFF"),
            (b"MM\x00*" + b"\x00" * 8, "TIFF"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(images.sniffed_format(data)[0], expected)

    def test_bytes_without_a_known_signature_are_unnamed(self):
        self.assertIsNone(images.sniffed_format(b"plain text, no magic"))
        self.assertIsNone(images.sniffed_format(b""))


@unittest.skipUnless(HAS_AVIF, "no AVIF decoder available to generate a fixture")
class AvifTranscodeTest(unittest.TestCase):
    def test_an_avif_is_stored_as_itself_with_a_readable_png(self):
        original = avif_bytes()
        prepared = images.prepared_image(original)
        self.assertEqual(prepared.mime, "image/avif")
        self.assertEqual(prepared.ext, "avif")
        self.assertEqual(prepared.format, "AVIF")
        self.assertEqual((prepared.width, prepared.height), (40, 20))
        self.assertEqual(prepared.data, original)
        readable = Image.open(BytesIO(prepared.readable.data))
        self.assertEqual(readable.format, "PNG")
        self.assertEqual((readable.width, readable.height), (40, 20))
        self.assertIsNotNone(prepared.thumb)
        self.assertIsNotNone(prepared.slim)


class OtherFormatTranscodeTest(unittest.TestCase):
    def test_a_bmp_is_transcoded_with_a_readable_png(self):
        original = bmp_bytes()
        prepared = images.prepared_image(original)
        self.assertEqual(prepared.mime, "image/bmp")
        self.assertEqual(prepared.ext, "bmp")
        self.assertEqual(prepared.format, "BMP")
        self.assertEqual(prepared.data, original)
        self.assertEqual(Image.open(BytesIO(prepared.readable.data)).format, "PNG")

    def test_an_animated_webp_gets_a_readable_first_frame(self):
        original = animated_webp_bytes()
        prepared = images.prepared_image(original)
        self.assertEqual(prepared.mime, "image/webp")
        self.assertEqual(prepared.data, original)
        readable = Image.open(BytesIO(prepared.readable.data))
        self.assertEqual(readable.format, "PNG")
        self.assertFalse(getattr(readable, "is_animated", False))

    def test_a_static_webp_needs_no_readable_tier(self):
        prepared = images.prepared_image(static_webp_bytes())
        self.assertIsNone(prepared.readable)
        self.assertIsNotNone(prepared.thumb)
        self.assertIsNotNone(prepared.slim)


@unittest.skipUnless(HAS_AVIF, "no AVIF fixture without a decoder")
class FfmpegFallbackTest(unittest.TestCase):
    def test_pillow_without_a_decoder_falls_back_to_ffmpeg(self):
        original = avif_bytes()
        real_open = images._open
        calls = {"n": 0}

        def pillow_has_no_plugin(data):
            calls["n"] += 1
            if calls["n"] == 1:
                raise images.UnidentifiedImageError("no AVIF support compiled in")
            return real_open(data)

        with mock.patch.object(images, "_open", side_effect=pillow_has_no_plugin):
            prepared = images.prepared_image(original)
        self.assertEqual(prepared.format, "AVIF")
        self.assertEqual(prepared.mime, "image/avif")
        self.assertEqual(Image.open(BytesIO(prepared.readable.data)).format, "PNG")
        self.assertEqual(prepared.data, original)

    def test_a_stalled_ffmpeg_is_a_missing_decoder(self):
        def nothing_opens(data):
            raise images.UnidentifiedImageError("unidentified")

        stalled = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)
        with mock.patch.object(images, "_open", side_effect=nothing_opens), mock.patch.object(
            formats.subprocess, "run", side_effect=stalled
        ):
            prepared = images.prepared_image(avif_bytes())
        self.assertIsNone(prepared.readable)
        self.assertEqual(prepared.format, "AVIF")


@unittest.skipUnless(HAS_AVIF, "no AVIF fixture without a decoder")
class UndecodableTest(unittest.TestCase):
    def test_an_upload_no_decoder_can_open_is_kept_and_marked(self):
        def nothing_opens(data):
            raise images.UnidentifiedImageError("unidentified")

        with mock.patch.object(images, "_open", side_effect=nothing_opens), mock.patch.object(
            formats, "_ffmpeg_png", return_value=None
        ):
            prepared = images.prepared_image(avif_bytes())
        self.assertEqual(prepared.mime, "image/avif")
        self.assertEqual(prepared.format, "AVIF")
        self.assertIsNone(prepared.readable)
        self.assertIsNone(prepared.thumb)
        self.assertIsNone(prepared.slim)

    def test_a_heic_signature_without_a_plugin_is_still_an_image(self):
        data = heic_signature_bytes()
        prepared = images.prepared_image(data)
        self.assertEqual(prepared.mime, "image/heic")
        self.assertEqual(prepared.ext, "heic")
        self.assertEqual(prepared.format, "HEIC")
        self.assertIsNone(prepared.readable)
        self.assertEqual(prepared.data, data)


class StoredDigestTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/chat.db")
        self.store = MediaStore(self.db, Path(self.directory.name) / "media")

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def _store_prepared(self, prepared_file):
        [ref] = self.store.store("line", 1, [prepared_file], "T", None)
        return ref, digest.digest_line(ref, "http://x")

    @unittest.skipUnless(HAS_AVIF, "no AVIF decoder available to generate a fixture")
    def test_an_avif_digest_labels_every_url_and_offers_the_readable_png(self):
        from partyline import media_files as files

        upload = files.prepared_file((avif_bytes(), "photo.avif", "image/avif"))
        ref, line = self._store_prepared(upload)
        self.assertEqual(ref.format, "AVIF")
        self.assertEqual(ref.readable.mime, "image/png")
        self.assertIn("readable: http://x/api/media/", line)
        self.assertIn("(PNG)", line)
        self.assertIn("thumb: http://x/api/media/", line)
        self.assertIn("original: http://x/api/media/", line)
        self.assertIn("(AVIF)", line)
        self.assertNotIn("not agent-readable", line)
        names = sorted(path.name for path in (self.store.root / "line").iterdir())
        self.assertIn(f"{ref.id}.avif", names)
        self.assertIn(f"{ref.id}_readable.png", names)

    def test_an_undecodable_digest_marks_the_original(self):
        from partyline import media_files as files

        upload = files.prepared_file(
            (heic_signature_bytes(), "photo.heic", "image/heic")
        )
        ref, line = self._store_prepared(upload)
        self.assertEqual(ref.kind, "image")
        self.assertIn("(HEIC)", line)
        self.assertIn("original format not agent-readable", line)
        self.assertNotIn("readable:", line)

    def test_a_direct_format_digest_stays_three_tier(self):
        from io import BytesIO

        from partyline import media_files as files

        buffer = BytesIO()
        Image.new("RGB", (40, 20)).save(buffer, format="PNG")
        upload = files.prepared_file((buffer.getvalue(), "a.png", "image/png"))
        ref, line = self._store_prepared(upload)
        self.assertNotIn("readable:", line)
        self.assertNotIn("not agent-readable", line)
        self.assertIn("(PNG)", line)


if __name__ == "__main__":
    unittest.main()
