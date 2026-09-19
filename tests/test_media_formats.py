"""Uploads in formats agents cannot natively decode: kept, labelled, readable.

Every fixture is generated in-process when a decoder exists, and the test
says so when it does not — a checked-in binary would make these tests a
statement about that file rather than about the pipeline.
"""

from io import BytesIO
from pathlib import Path
import base64
import os
import shutil
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


def avif_signature_bytes() -> bytes:
    """AVIF magic without needing an encoder: enough for the sniff layer."""
    return b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00avifmif1" + b"\x00" * 8


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


class FfmpegArgvTest(unittest.TestCase):
    def test_the_decoder_is_capped_at_the_pixel_ceiling(self):
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            Path(argv[-1]).write_bytes(b"png")
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch.object(formats, "decodes", return_value=True), mock.patch.object(
            formats.shutil, "which", return_value="/usr/bin/ffmpeg"
        ), mock.patch.object(formats.subprocess, "run", side_effect=fake_run):
            produced = formats._ffmpeg_png(b"junk", "AVIF")
        self.assertEqual(produced, b"png")
        self.assertIn("-max_pixels", captured["argv"])
        self.assertEqual(
            captured["argv"][captured["argv"].index("-max_pixels") + 1],
            str(formats.MAX_PIXELS),
        )


def stub_ffmpeg_script() -> str:
    """A fake ffmpeg: answers ``-decoders``, transcodes to a real PNG.

    The listing line ends in ``(codec av1)`` exactly like the real tool's,
    so the capability probe reads it the same way it reads ffmpeg itself.
    """
    buffer = BytesIO()
    Image.new("RGB", (4, 2), (1, 2, 3)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"""#!/usr/bin/env python3
import base64, os, sys
args = sys.argv[1:]
if "-decoders" in args:
    marker = os.environ.get("FAKE_FFMPEG_PROBE_FILE")
    if marker:
        with open(marker, "a") as tally:
            tally.write("probe\\n")
    print(" V....D fake-av1            fake AV1 decoder (codec av1)")
    sys.exit(0)
with open(args[-1], "wb") as out:
    out.write(base64.b64decode({encoded!r}))
"""


@unittest.skipUnless(HAS_AVIF, "no AVIF fixture without a decoder")
class FfmpegFallbackTest(unittest.TestCase):
    """The real ffmpeg on this machine, probed by actually rescuing once."""

    rescue_works = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A capability listing alone proved insufficient: a machine can list
        # an AV1 decoder yet still fail to demux AVIF or reject -max_pixels,
        # and the test then errored on a None readable exactly the way CI
        # once did. Probe by running the real rescue once; when it cannot
        # produce a PNG, ffmpeg's own error is in the warning logged here.
        if HAS_AVIF and shutil.which("ffmpeg") and formats.decodes("AVIF"):
            cls.rescue_works = formats._ffmpeg_png(avif_bytes(), "AVIF") is not None

    def setUp(self):
        if not self.rescue_works:
            self.skipTest(
                "the setUpClass rescue probe produced no PNG — ffmpeg's reason "
                "is in the warning it logged just above"
            )

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
        self.assertIsNotNone(prepared.readable)
        self.assertEqual(Image.open(BytesIO(prepared.readable.data)).format, "PNG")
        self.assertEqual(prepared.data, original)


class FakeFfmpegTest(unittest.TestCase):
    """The fallback logic with a stub ffmpeg on PATH: no real tool required."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.bin = Path(self.directory.name) / "bin"
        self.bin.mkdir()
        self.install_stub(stub_ffmpeg_script())
        self.original_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{self.original_path}"
        formats.reset_decoder_probe()

    def tearDown(self):
        os.environ["PATH"] = self.original_path
        os.environ.pop("FAKE_FFMPEG_PROBE_FILE", None)
        formats.reset_decoder_probe()
        self.directory.cleanup()

    def install_stub(self, script: str) -> None:
        stub = self.bin / "ffmpeg"
        stub.write_text(script)
        stub.chmod(0o755)

    def test_a_stub_ffmpeg_on_path_rescues_the_upload(self):
        image = formats.rescued(avif_signature_bytes(), ("AVIF", "image/avif", "avif"))
        self.assertIsNotNone(image)
        self.assertEqual((image.width, image.height), (4, 2))

    def test_a_stalled_ffmpeg_is_a_missing_decoder(self):
        def nothing_opens(data):
            raise images.UnidentifiedImageError("unidentified")

        stalled = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)
        with mock.patch.object(images, "_open", side_effect=nothing_opens), mock.patch.object(
            formats, "decodes", return_value=True
        ), mock.patch.object(formats.subprocess, "run", side_effect=stalled):
            prepared = images.prepared_image(avif_signature_bytes())
        self.assertIsNone(prepared.readable)
        self.assertEqual(prepared.format, "AVIF")

    def test_the_capability_probe_runs_once_per_process(self):
        marker = self.bin / "probes"
        os.environ["FAKE_FFMPEG_PROBE_FILE"] = str(marker)
        self.assertTrue(formats.decodes("AVIF"))
        self.assertTrue(formats.decodes("AVIF"))
        self.assertEqual(marker.read_text(), "probe\n")

    def test_an_argv_rejecting_ffmpeg_is_a_logged_error_not_silence(self):
        self.install_stub(
            "#!/bin/sh\n"
            'if [ "$1" = "-hide_banner" ]; then\n'
            "  echo ' V....D fake-av1            fake AV1 decoder (codec av1)'\n"
            "  exit 0\n"
            "fi\n"
            "echo \"Unrecognized option 'max_pixels'.\" 'Error splitting the argument list: "
            "Option not found' >&2\n"
            "exit 2\n"
        )
        formats.reset_decoder_probe()
        with self.assertLogs("partyline.media_formats", level="ERROR") as seen:
            self.assertIsNone(formats._ffmpeg_png(avif_signature_bytes(), "AVIF"))
        self.assertIn("max_pixels", seen.output[0])

    def test_a_ffmpeg_that_fails_to_probe_reports_no_decoder(self):
        with mock.patch.object(formats.subprocess, "run", side_effect=OSError("gone")):
            self.assertFalse(formats.decodes("AVIF"))
        self.assertEqual(formats.ffmpeg_decoders(), "")

    def test_a_failing_probe_run_also_reports_no_decoder(self):
        with mock.patch.object(
            formats.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)
        ):
            self.assertFalse(formats.decodes("AVIF"))

    def test_a_listing_of_native_decoders_reads_capable_by_name(self):
        listing = subprocess.CompletedProcess([], 0)
        listing.stdout = (
            b"Decoders:\n"
            b" V....D av1                  Alliance for Open Media AV1\n"
            b" V....D hevc                 native HEVC (native)\n"
            b" A....D opus                 Opus (codec opus)\n"
            b" -------\n"
        )
        with mock.patch.object(formats.subprocess, "run", return_value=listing):
            self.assertTrue(formats.decodes("AVIF"))
            self.assertTrue(formats.decodes("HEIC"))

    def test_a_listing_without_the_codec_reports_no_decoder(self):
        listing = subprocess.CompletedProcess([], 0)
        listing.stdout = b" V....D fake-mpeg4            fake (codec mpeg4)\n"
        with mock.patch.object(formats.subprocess, "run", return_value=listing):
            self.assertFalse(formats.decodes("AVIF"))
            self.assertFalse(formats.decodes("HEIC"))

    def test_an_absent_ffmpeg_is_logged_and_not_a_rescue(self):
        with mock.patch.object(formats.shutil, "which", return_value=None):
            with self.assertLogs("partyline.media_formats", level="INFO") as seen:
                self.assertIsNone(formats._ffmpeg_png(b"junk", "AVIF"))
        self.assertIn("not on PATH", seen.output[0])

    def test_an_unsupported_format_is_logged_and_not_a_rescue(self):
        with mock.patch.object(formats, "decodes", return_value=False):
            with self.assertLogs("partyline.media_formats", level="INFO") as seen:
                self.assertIsNone(formats._ffmpeg_png(b"junk", "JXL"))
        self.assertIn("no JXL decoder", seen.output[0])

    def test_a_format_ffmpeg_has_no_business_with_is_not_probed(self):
        self.assertFalse(formats.decodes("PNG"))


class UndecodableTest(unittest.TestCase):
    def test_an_upload_no_decoder_can_open_is_kept_and_marked(self):
        def nothing_opens(data):
            raise images.UnidentifiedImageError("unidentified")

        with mock.patch.object(images, "_open", side_effect=nothing_opens), mock.patch.object(
            formats, "_ffmpeg_png", return_value=None
        ):
            prepared = images.prepared_image(avif_signature_bytes())
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
