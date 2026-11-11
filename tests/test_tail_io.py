import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.adapters import jsonl_receipts
from partyline.adapters.events import AdapterEvents


class Adapter(AdapterEvents):
    def __init__(self):
        self._events_init()
    att = {"name": "test"}
    live = True
    def recorded_claim(self, path): return False
    def foreign_claim(self, path): return False
    def _claim_in_line(self, line): return False
    def _mark_claim_proven(self): pass
    def mark_ready(self): pass
    def alive(self): return self.live
    async def _observe_jsonl_paste(self, record): pass
    async def post(self, *args): pass


class TailIOTest(unittest.IsolatedAsyncioTestCase):
    async def test_split_utf8_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript"
            path.write_bytes(b'{"n":"\xe2')
            pending = bytearray()
            anchor = bytearray()
            with path.open("rb", buffering=0) as file:
                lines, _, _ = jsonl_receipts._read_batch(file, pending, str(path), anchor)
                self.assertEqual(lines, [])
                with path.open("ab") as out:
                    out.write(b'\x82\xac"}\n')
                lines, _, _ = jsonl_receipts._read_batch(file, pending, str(path), anchor)
                self.assertEqual(lines[0][1], {"n": "€"})
                path.write_bytes(b'{}\n')
                lines, _, _ = jsonl_receipts._read_batch(file, pending, str(path), anchor)
                self.assertEqual(lines[0][1], {})
                path.write_bytes(b'{"replacement":true}\n')
                lines, _, _ = jsonl_receipts._read_batch(file, pending, str(path), anchor)
                self.assertEqual(lines[0][1], {"replacement": True})

    async def test_incremental_read_off_loop_and_partial_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript"
            path.write_bytes(b'{"n":1}\n' + b' ' * 140000)
            adapter = Adapter()
            observed = []
            loop_thread = threading.get_ident()
            calls = []
            initial_reads = threading.Event()
            first_record = asyncio.Event()
            second_record = asyncio.Event()
            original = jsonl_receipts._read_batch

            def read(file, pending, name, anchor):
                start = file.tell()
                result = original(file, pending, name, anchor)
                calls.append((threading.get_ident(), file.tell() - start))
                if len(calls) >= 4:
                    initial_reads.set()
                return result

            async def handle(record):
                observed.append(record)
                first_record.set()
                if len(observed) == 2:
                    second_record.set()

            with patch.object(jsonl_receipts, "_read_batch", read):
                task = asyncio.create_task(jsonl_receipts.tail_jsonl(adapter, str(path), handle))
                self.assertTrue(await asyncio.to_thread(initial_reads.wait, 2))
                await asyncio.wait_for(first_record.wait(), 2)
                self.assertEqual(observed, [{"n": 1}])
                self.assertTrue(all(t != loop_thread and n <= 65536 for t, n in calls))
                replacement = path.with_suffix('.new')
                replacement.write_text(json.dumps({"n": 2}) + '\n')
                os.replace(replacement, path)
                await asyncio.wait_for(second_record.wait(), 2)
                adapter.live = False
                adapter.changed()
                await asyncio.wait_for(task, 2)
                self.assertEqual(observed, [{"n": 1}, {"n": 2}])
