"""Captured-pointer regressions use generated pixels and virtual timestamps only."""
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from partyline.screen_frames import BufferedFrame
from partyline.screen_pointer import captured_pointer, annotate_stationary_pointers
from partyline.screen_protocol import Pointer
from partyline.screen_routes import _mark_pointer, frame_detail, pointer_coordinates
from partyline.walkthrough import assemble_message, deduplicate_frames, select_frames
from partyline_helper import desktop


def frame(color="gray", x=2705, y=1151, **pointer):
    data = BytesIO()
    Image.new("RGB", (320, 180), color).save(data, format="PNG")
    return BufferedFrame(data.getvalue(), 0, dict(x=2500, y=1000, width=640, height=360),
                         320, 180, dict(x=x, y=y, visible=True, **pointer), "image/png")


class CapturedPointerTest(unittest.TestCase):
    def test_game_hidden_pointer_labels_changed_frames_and_keeps_pixels(self):
        frames = [replace(frame(color, captured=True), ts_ms=i * 1000) for i, color in
                  enumerate(("red", "green", "blue", "blue"))]
        selected = select_frames(frames, [])
        self.assertEqual(len(selected), 3)
        self.assertEqual([f.data for f in selected], [f.data for f in frames[:3]])
        text = assemble_message("", [], selected)
        self.assertEqual(text.count("(view centre; pointer captured)"), 3)
        self.assertNotIn("2705", text)
        self.assertTrue(all(captured_pointer(f) for f in frames))

    def test_jitter_duplicates_and_selection_preserve_full_take_evidence(self):
        frames = [frame("red", x=2705), frame("red", x=2706), frame("blue", x=2708)]
        selected = select_frames(frames, [], count=2)
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(f.pointer.get("stationary") for f in selected))
        self.assertFalse(any(captured_pointer(f) for f in selected))
        text = assemble_message("", [], annotate_stationary_pointers(frames))
        self.assertEqual(text.count(", stationary)"), 3)
        hidden = [frame("red", captured=True), frame("red", x=2800, captured=True),
                  frame("blue", x=2800, captured=True)]
        self.assertEqual(deduplicate_frames(hidden), [hidden[0], hidden[2]])
        self.assertEqual(len(deduplicate_frames([hidden[0], frame("red")])), 2)

    def test_moving_pointer_idle_screen_and_short_runs_keep_coordinates(self):
        for frames in ([frame("red", x=2705), frame("green", x=2715), frame("blue", x=2725)],
                       [frame(), frame(), frame()], [frame("red"), frame("blue")]):
            with self.subTest(frames=len(frames)):
                self.assertFalse(any(f.pointer and f.pointer.get("stationary")
                                 for f in annotate_stationary_pointers(frames)))
                text = assemble_message("", [], frames)
                self.assertIn("pointer at 2705,1151", text)
                self.assertNotIn("view centre", text)
                self.assertNotIn("stationary", text)

    def test_region_missing_pointer_and_slow_drift_break_runs(self):
        base = frame()
        for frames in ([base, replace(frame("red"), region=dict(x=0)), frame("blue")],
                       [base, replace(base, out_width=300), frame("blue")],
                       [base, replace(base, pointer=None), frame("blue")],
                       [frame(color, x=2705+i*2) for i, color in
                        enumerate(("red", "green", "blue", "white"))]):
            self.assertFalse(any(f.pointer and f.pointer.get("stationary")
                                 for f in annotate_stationary_pointers(frames)))
        # Unreadable images must not count as identical.
        self.assertEqual(len(deduplicate_frames([replace(base, data=b"bad"), base])), 2)
        self.assertEqual(len(deduplicate_frames([base, replace(base, region={})])), 2)

    def test_wheel_scroll_video_and_typing_keep_real_pointer_labels_and_markers(self):
        # These activities all leave a visible cursor resting over changing pixels.
        for activity in ("wheel scroll", "video playback", "typing"):
            with self.subTest(activity=activity):
                frames = [frame(color) for color in ("red", "green", "blue")]
                selected = select_frames(frames, [])
                text = assemble_message("", [], selected)
                self.assertEqual(text.count("(pointer at 2705,1151, stationary)"), 3)
                self.assertNotIn("view centre", text)
                self.assertFalse(any(captured_pointer(f) for f in selected))
                self.assertFalse(any(f.pointer.get("stationary") for f in frames))
                for f in selected:
                    self.assertEqual(pointer_coordinates(f)["frame"], {"x": 102, "y": 75})
                    marked = Image.open(BytesIO(_mark_pointer(f)))
                    original = Image.open(BytesIO(f.data))
                    self.assertEqual(marked.getpixel((102, 75)), (255, 255, 255))
                    self.assertEqual(marked.getpixel((160, 90)), original.getpixel((160, 90)))
        # A stationary annotation must not disable the ordinary pointer-position check.
        first, moved = frame(), frame(x=2720)
        first.pointer["stationary"] = moved.pointer["stationary"] = True
        self.assertEqual(deduplicate_frames([first, moved]), [first, moved])

    def test_hidden_cursor_protocol_labels_and_centre_crosshair(self):
        image = frame(captured=True)
        image.pointer["visible"] = False
        image.pointer = Pointer.model_validate(image.pointer).model_dump()
        self.assertTrue(captured_pointer(image))
        self.assertIn("view centre; pointer captured", assemble_message("", [], [image]))
        self.assertEqual(pointer_coordinates(image), {"os": None, "frame": {"x": 160, "y": 90}})
        self.assertIn("view centre; pointer captured", frame_detail(image))
        marked = Image.open(BytesIO(_mark_pointer(image)))
        original = Image.open(BytesIO(image.data))
        self.assertEqual(marked.getpixel((160, 90)), (255, 255, 255))
        self.assertEqual(marked.getpixel((102, 75)), original.getpixel((102, 75)))
        ordinary = frame()
        self.assertNotEqual(_mark_pointer(ordinary), ordinary.data)
        invisible = replace(ordinary, pointer=None)
        self.assertEqual(_mark_pointer(invisible), invisible.data)
        outside = replace(ordinary, pointer=dict(x=0, y=0, visible=True))
        self.assertEqual(pointer_coordinates(outside), {"os": None, "frame": None})

    def test_windows_hidden_visible_and_failed_cursor_queries(self):
        def query(info):
            self.assertEqual(info._obj.cbSize, desktop.ctypes.sizeof(info._obj))
            info._obj.flags = _flags
            return _success
        user32 = SimpleNamespace(GetCursorInfo=query)
        with patch.object(desktop.sys, "platform", "win32"), patch.object(
                desktop.ctypes, "windll", SimpleNamespace(user32=user32), create=True):
            for _flags, _success, expected in ((0, 1, True), (1, 1, False), (0, 0, False),
                                              (2, 1, True)):
                self.assertEqual(desktop.cursor_hidden(), expected)
        with patch.object(desktop.sys, "platform", "linux"):
            self.assertFalse(desktop.cursor_hidden())
