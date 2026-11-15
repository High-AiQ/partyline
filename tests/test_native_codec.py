"""Native framing, hostile input bounds, and partial pipe reads."""
import io
import json
import struct
import unittest

from partyline_helper.native_codec import (Decoder, FRAME_LIMIT, MESSAGE_LIMIT, frame, length,
                                           packets, read_exact, read_frame)


class CodecTests(unittest.TestCase):
    def test_native_32bit_prefix_and_partial_reads(self):
        raw = frame({"hello": "world"})
        self.assertEqual(struct.unpack("=I", raw[:4])[0], len(raw) - 4)
        self.assertEqual(read_frame(io.BytesIO(raw)), {"hello": "world"})
        class Partial(io.BytesIO):
            def read(self, count):
                return super().read(min(1, count))
        self.assertEqual(read_frame(Partial(raw)), {"hello": "world"})
        with self.assertRaises(EOFError):
            read_frame(io.BytesIO())
        with self.assertRaises(ValueError):
            read_exact(io.BytesIO(b"a"), 2)

    def test_limits_and_malformed_frames(self):
        for size in (0, FRAME_LIMIT + 1):
            with self.assertRaises(ValueError):
                length(struct.pack("=I", size))
        with self.assertRaises(ValueError):
            frame({"value": "x" * FRAME_LIMIT})
        with self.assertRaises(ValueError):
            packets({"value": "x" * MESSAGE_LIMIT})
        with self.assertRaises(ValueError):
            read_frame(io.BytesIO(struct.pack("=I", 1) + b"x"))

    def test_chunk_large_unicode_ax_result(self):
        message = {"id": 9, "result": {"nodes": ["💻" * 150000]}}
        chunks = packets(message)
        self.assertGreater(len(chunks), 1)
        decoder = Decoder()
        for part in chunks:
            self.assertLessEqual(len(frame(part)) - 4, FRAME_LIMIT)
            result = decoder.accept(part)
        self.assertEqual(result, message)
        self.assertEqual(decoder.accept({"id": 10}), {"id": 10})

    def test_corrupt_or_unbounded_chunk_stream(self):
        for value in ([], {"chunk": {"index": 1, "total": 2, "data": "x"}},
                      {"chunk": {"index": 0, "total": 257, "data": "x"}},
                      {"chunk": {"index": 0, "total": 2, "data": 5}},
                      {"chunk": {"index": 0, "total": 2, "data": "x" * (MESSAGE_LIMIT + 1)}}):
            with self.assertRaises(ValueError):
                Decoder().accept(value)
        decoder = Decoder()
        decoder.accept({"chunk": {"index": 0, "total": 2, "data": "{"}})
        with self.assertRaises(ValueError):
            decoder.accept({"id": 1})
        with self.assertRaises(ValueError):
            decoder.accept({"chunk": {"index": 1, "total": 3, "data": "}"}})
        for value in ('[]', 'bad'):
            decoder = Decoder()
            decoder.accept({"chunk": {"index": 0, "total": 2, "data": value[:1]}})
            with self.assertRaises(ValueError):
                decoder.accept({"chunk": {"index": 1, "total": 2, "data": value[1:]}})
        self.assertEqual(json.loads(frame({"a": 1})[4:]), {"a": 1})
