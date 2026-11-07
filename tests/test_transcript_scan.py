import tempfile
import unittest
from pathlib import Path

from partyline.adapters.transcript_scan import scan_lines


class ScanLinesTest(unittest.TestCase):
    def scan(self, text: str, limit: int) -> list[str]:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "t.jsonl"
            path.write_text(text, encoding="utf-8")
            return list(scan_lines(str(path), limit))

    def test_a_small_file_is_read_whole_once(self):
        self.assertEqual(self.scan("a\nb\nc\n", 100), ["a\n", "b\n", "c\n"])

    def test_a_large_file_yields_head_and_tail_without_the_middle(self):
        lines = [f"{i:03d}\n" for i in range(100)]  # 4 bytes each
        got = self.scan("".join(lines), 40)
        self.assertEqual(got[:10], lines[:10])
        self.assertEqual(got[10:], lines[90:])  # a line starting on the boundary is whole
        self.assertEqual(len(got), len(set(got)))

    def test_windows_that_meet_do_not_repeat_lines(self):
        lines = [f"{i:03d}\n" for i in range(12)]
        got = self.scan("".join(lines), 40)
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(got[0], lines[0])
        self.assertEqual(got[-1], lines[-1])

    def test_an_empty_file_yields_nothing(self):
        self.assertEqual(self.scan("", 10), [])

    def test_a_line_longer_than_the_window_is_skipped_not_split(self):
        got = self.scan("head\n" + "x" * 100 + "\ntail\n", 10)
        self.assertEqual(got, ["head\n", "tail\n"])

    def test_a_record_crossing_the_head_boundary_is_seen_whole_in_the_tail(self):
        """A complete record in the tail window survives the head rejecting it."""
        lines = ["a" * 20 + "\n", "b" * 20 + "\n", "CLAIM\n", "c" * 20 + "\n"]
        # limit 45: the head takes lines 0-1 (42 bytes) and rejects CLAIM
        # (48 > 45); the 69-byte file's tail window starts at byte 24, so
        # CLAIM lies whole inside it.
        got = self.scan("".join(lines), 45)
        self.assertIn("CLAIM\n", got)
        self.assertEqual(len(got), len(set(got)))

    def test_overlapping_windows_yield_each_line_once_in_order(self):
        lines = [f"{'x' * (i % 7 + 1)}{i:02d}\n" for i in range(30)]
        text = "".join(lines)
        for limit in range(1, len(text) + 2):
            with self.subTest(limit=limit):
                got = self.scan(text, limit)
                self.assertEqual(len(got), len(set(got)))
                self.assertEqual(got, sorted(got, key=lines.index))
