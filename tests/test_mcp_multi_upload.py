"""Multi-file MCP uploads through a real HTTP server and multipart parser."""

from io import BytesIO
from pathlib import Path

from PIL import Image

from partyline.mcp import tools_core
from partyline.mcp.client import ApiError, CHUNK, MAX_UPLOAD
from partyline.mcp.uploads import MAX_TOTAL_UPLOAD
from tests import test_mcp_upload_roundtrip as roundtrip


class MCPMultiUploadTests(roundtrip.MCPUploadRoundtripTests):
    def paths(self, names, payloads):
        paths = []
        for name, payload in zip(names, payloads, strict=True):
            path = Path(self.directory.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            paths.append(str(path))
        return paths

    def count(self):
        return self.db._exec("SELECT COUNT(*) FROM messages").fetchone()[0]

    def test_six_texts_preserve_bytes_order_metadata_and_retry(self):
        payloads = [b"one\r\ntwo\r\n", b"binary\x00\xff\r\n", b"final\n\n",
                    b"no newline", b"chunk\r\n" * (CHUNK // 6 + 10), b"six"]
        names = ['one\r\n".txt', 'one___ directory/two.txt', 'a/same.txt',
                 'b/same.txt', 'five.txt', 'six.txt']
        paths = self.paths(names, payloads)
        client = self.client()
        result = client.upload_files("line", paths, client_key="six-text",
                                     title="batch", description="description", body="caption")
        self.assertEqual(len(result["files"]), 6)
        self.assertEqual(len(result["message"]["files"]), 6)
        self.assertEqual(self.count(), 1)
        self.assertEqual(result["message"]["body"].splitlines()[0], "caption")
        stored_names = [ref["filename"] for ref in result["files"]]
        self.assertEqual(stored_names, ['one___.txt', 'two.txt', 'same.txt', 'same-2.txt',
                                       'five.txt', 'six.txt'])
        for ref, payload in zip(result["files"], payloads, strict=True):
            self.assertEqual(self.download(client, ref), payload)
            self.assertEqual(ref["title"], "batch")
            self.assertEqual(ref["description"], "description")
        replay = client.upload_files("line", paths[::-1], client_key="six-text")
        self.assertEqual(result["message"]["id"], replay["message"]["id"])
        self.assertTrue(replay["message"]["replayed"])
        self.assertEqual([f["id"] for f in result["files"]], [f["id"] for f in replay["files"]])
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.db._exec("SELECT COUNT(*) FROM images").fetchone()[0], 6)

    def test_six_images_and_mixed_files_have_real_variants(self):
        dimensions = [(1800, 1200), (600, 1800), (1800, 1800),
                      (2400, 900), (1700, 1200), (600, 2000)]
        payloads = []
        for index, size in enumerate(dimensions):
            output = BytesIO()
            Image.new("RGB", size, (index * 40, 60, 100)).save(
                output, format="JPEG" if index % 2 else "PNG")
            payloads.append(output.getvalue())
        # Misleading suffixes prove the server uses content detection.
        paths = self.paths([f"image-{i}.txt" for i in range(6)], payloads)
        client = self.client()
        result = client.upload_files("line", paths, client_key="six-images")
        self.assertEqual(len(result["files"]), 6)
        for ref, size, payload in zip(result["files"], dimensions, payloads, strict=True):
            self.assertEqual(self.download(client, ref), payload)
            for variant, bound in (("thumb", 512), ("slim", 1600), ("original", max(size))):
                destination = Path(self.directory.name) / f"{ref['id']}-{variant}"
                client.download(ref["id"], variant, str(destination))
                with Image.open(destination) as image:
                    expected = Image.new("RGB", size)
                    expected.thumbnail((bound, bound))
                    self.assertEqual(image.size, expected.size)
                    self.assertLessEqual(max(image.size), bound)
                if variant == "thumb":
                    self.assertLessEqual(destination.stat().st_size, 256 * 1024)
        text = self.paths(["mixed.txt"], [b"mixed\r\n\x00\n"])[0]
        mixed = client.upload_files("line", [paths[0], text, paths[1]], client_key="mixed")
        self.assertEqual(len(mixed["files"]), 3)
        for ref, payload in zip(mixed["files"], [payloads[0], b"mixed\r\n\x00\n", payloads[1]],
                                strict=True):
            self.assertEqual(self.download(client, ref), payload)
        self.assertEqual(self.count(), 2)

    def test_invalid_batches_fail_before_connection_and_create_no_message(self):
        valid = self.paths(["valid.txt"], [b"valid"])[0]
        huge = Path(self.directory.name) / "oversize.bin"
        with huge.open("wb") as stream:
            stream.truncate(MAX_UPLOAD + 1)
        aggregate = []
        for index in range(4):
            path = Path(self.directory.name) / f"large-{index}"
            with path.open("wb") as stream:
                stream.truncate(MAX_TOTAL_UPLOAD // 4 + 1)
            aggregate.append(str(path))
        client = self.client()
        def forbidden_origin():
            self.fail("invalid batch opened a connection")
        client._origin = forbidden_origin
        cases = [[], [valid] * 7, [valid, str(huge)], aggregate,
                 [str(Path(self.directory.name))], [valid, valid + ".missing"]]
        for paths in cases:
            with self.subTest(paths=paths), self.assertRaises((ValueError, OSError)):
                client.upload_files("line", paths, client_key="invalid")
        for metadata in ({"client_key": ""}, {"client_key": "x" * 65},
                         {"client_key": "key", "title": "x" * 201},
                         {"client_key": "key", "description": "x" * 2001},
                         {"client_key": "key", "body": "x" * 3001}):
            with self.assertRaises(ValueError):
                client.upload_files("line", [valid], **metadata)
        self.assertEqual(self.count(), 0)

    def test_size_changes_after_preflight_abort_the_real_request(self):
        for changed in (b"short", b"longer than the original payload"):
            paths = self.paths(["changing.txt"], [b"original payload"])
            client = self.client()
            origin = client._origin
            def changing_origin(paths=paths, changed=changed, origin=origin):
                Path(paths[0]).write_bytes(changed)
                return origin()
            client._origin = changing_origin
            with self.assertRaisesRegex(ValueError, "file changed"):
                client.upload_files("line", paths, client_key="changing")
        self.assertEqual(self.count(), 0)

    def test_tool_authorization_caption_refusal_and_real_http_denial(self):
        paths = self.paths(["authorized.txt"], [b"authorized"])
        client = self.client()
        args = {"paths": paths, "client_key": "auth"}
        with self.assertRaisesRegex(ApiError, "not authorized"):
            tools_core.call(client, "upload_files", args, {"actions": ["read"]})
        with self.assertRaisesRegex(ValueError, "cannot post free prose"):
            tools_core.call(client, "upload_files", {**args, "body": "caption"},
                            {"actions": ["write"]})
        with self.assertRaisesRegex(ApiError, "HTTP 403"):
            client.upload_files("other", paths, client_key="denied")
        self.assertEqual(self.count(), 0)
        result = tools_core.call(client, "upload_files", args, {"actions": ["write"]})
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(self.count(), 1)
