import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from partyline.screen_frames import BufferedFrame, ShareBuffer
from partyline.walkthrough import (WalkthroughBuffer, assemble_message, deduplicate_frames,
                                   select_frames, speech_segments)
from partyline.walkthrough_takes import Takes


def frame(timestamp, data=None):
    return BufferedFrame(data or str(timestamp).encode(), timestamp, {}, 1, 1, None, "image/png")


class WalkthroughTest(unittest.TestCase):
    def test_pause_uses_frame_before_sentence_end_and_keeps_endpoints(self):
        frames = [frame(t) for t in (0, 1000, 2000, 3000, 4000)]
        segments = [{"start": 0, "end": 1.5, "text": "first"},
                    {"start": 2.5, "end": 3, "text": "second"}]
        self.assertEqual(select_frames(frames, segments, 3), [frames[0], frames[1], frames[-1]])

    def test_distinct_frames_and_small_limits(self):
        frames = [frame(0, b"a"), frame(100, b"b"), frame(200, b"b"), frame(300, b"c")]
        self.assertEqual(select_frames(frames, [], 4), [frames[0], frames[1], frames[3]])
        self.assertEqual(select_frames(frames, [], 0), [])
        self.assertEqual(select_frames(frames, [], 1), frames[:1])
        self.assertEqual(select_frames([], []), [])

    def test_selection_spans_a_long_take_with_a_fixed_budget(self):
        frames = [frame(i * 1000) for i in range(100)]
        selected = select_frames(frames, [])
        self.assertEqual(len(selected), 24)
        self.assertIs(selected[0], frames[0])
        self.assertIs(selected[-1], frames[-1])
        self.assertTrue(any(item.ts_ms >= 45_000 and item.ts_ms <= 55_000 for item in selected))

    def test_buffer_caps_and_clear(self):
        buffer = WalkthroughBuffer(max_duration_ms=100, max_frames=3, max_bytes=6)
        items = [frame(t, b"xx") for t in (0, 20, 40, 60)]
        for item in items:
            self.assertTrue(buffer.add(item))
        self.assertEqual(buffer.frames, [items[0], items[2], items[3]])
        self.assertEqual(buffer.size, 6)
        self.assertFalse(buffer.add(frame(101)))
        self.assertFalse(buffer.add(frame(50)))
        self.assertFalse(buffer.add(frame(80, b"too large")))
        buffer.clear()
        self.assertEqual(buffer.frames, [])
        self.assertEqual(buffer.size, 0)

    def test_byte_limit_can_evict_first_frame(self):
        buffer = WalkthroughBuffer(max_frames=2, max_bytes=3)
        buffer.add(frame(0, b"aa"))
        buffer.add(frame(1, b"bb"))
        self.assertEqual([item.ts_ms for item in buffer.frames], [1])
        self.assertEqual(buffer.size, 2)
        buffer.max_duration_ms = 100
        self.assertFalse(buffer.add(frame(101, b"x")))

    def test_message_orders_notes_segments_and_visible_pointer(self):
        image = BufferedFrame(b"x", 1200, {"x": 10, "y": 20, "width": 100, "height": 100},
                              10, 10, {"x": 12, "y": 24, "visible": True}, "image/png")
        body = assemble_message("notes", [{"start": 0, "end": 1, "text": "click"}], [image], True)
        self.assertEqual(body, 'Walkthrough · 0:01 · 1 frame\nnotes\n'
                         'Contact sheet first: open it, then fetch only the frames you need '
                         '(thumb ≈ 230 tokens, slim ≈ 1,400).\nSpeech transcription failed; '
                         'the screen frames are included below.\n'
                         '[0:00] "click"\n[0:01] → frame 1 (pointer at 12,24)')
        image.pointer["x"] = 500
        self.assertNotIn("pointer at", assemble_message("", [], [image]))
        self.assertIn("no speech", assemble_message("", [], []))
        self.assertIn("no screen frames", assemble_message("", [], [], True))

    def test_silence_and_sentence_boundaries(self):
        def segment(text, start, end):
            return {"text": text, "start": start, "end": end}
        fake = [segment("You!", 0, 1), segment(" THANK YOU. ", 2, 3)]
        self.assertEqual(speech_segments(fake, False), [])
        self.assertEqual(speech_segments([segment("you, YOU!", 0, 2)], False), [])
        self.assertEqual(speech_segments([segment("Thanks... for watching!", 0, 1)] * 2, False), [])
        repetition = segment("bye " * 2000 + "hello", 0, 1)
        self.assertEqual(speech_segments([repetition], False), [repetition])
        self.assertEqual(speech_segments([segment("Hello there", 0, 1)], True), [])
        actual = [segment("Now I", 0, 1), segment("have my mouse over it.", 1.1, 2),
                  segment("Thank you.", 3, 4)]
        joined = speech_segments(actual, False)
        self.assertEqual([item["text"] for item in joined],
                         ["Now I have my mouse over it.", "Thank you."])
        self.assertIn("(no speech detected — check the microphone)", assemble_message("", [], []))

    def test_deduplicate_near_frames_without_losing_pointer_changes(self):
        from io import BytesIO
        from PIL import Image
        def image(color, x):
            data = BytesIO()
            Image.new("RGB", (16, 16), color).save(data, format="PNG")
            return BufferedFrame(data.getvalue(), x * 100, {"x": 0, "y": 0, "width": 100, "height": 100},
                                 16, 16, {"x": x, "y": 10, "visible": True}, "image/png")
        first, near, moved, changed = image((100, 100, 100), 10), image((100, 100, 101), 12), \
            image((100, 100, 100), 20), image((0, 0, 0), 20)
        self.assertEqual(deduplicate_frames([first, near, moved, changed]), [first, moved, changed])
        self.assertEqual(select_frames([first, near, moved, changed], []), [first, moved, changed])


class TakeBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_total_budget_applies_across_active_takes_and_frees_on_discard(self):
        takes = Takes(None)
        takes.bytes = takes.total_bytes = 5
        first = ShareBuffer("a", "line-a", "device-a", 1, "alice", {})
        second = ShareBuffer("b", "line-b", "device-b", 1, "alice", {})
        one, two = takes.create(first), takes.create(second)
        takes.arm(one, first)
        takes.arm(two, second)
        takes.add(first, frame(0, b"abc"))
        takes.add(second, frame(0, b"xyz"))
        self.assertEqual((one.buffer.size, two.buffer.size), (3, 0))
        takes.discard("a")
        takes.add(second, frame(0, b"xyz"))
        self.assertEqual(two.buffer.size, 3)
        takes.discard("b")

    async def test_expiry_stops_the_share_and_clears_frames(self):
        hub = SimpleNamespace(stop_share=AsyncMock())
        takes = Takes(hub)
        share = ShareBuffer("a", "line", "device", 1, "alice", {})
        take = takes.create(share)
        takes.arm(take, share)
        takes.add(share, frame(0, b"image"))
        await takes.expire(take)
        hub.stop_share.assert_awaited_once_with("a", "walkthrough stopped")
        self.assertFalse(take.buffer.frames)
        self.assertNotIn("a", takes.items)


if __name__ == "__main__":
    unittest.main()
