"""Contact sheet geometry and labels use the same order as the timeline."""
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from partyline.screen_frames import BufferedFrame
from partyline.walkthrough_sheet import contact_sheet


class ContactSheetTest(unittest.TestCase):
    def test_layout_and_labels(self):
        image = BytesIO()
        Image.new("RGB", (40, 20), "red").save(image, format="PNG")
        frames = [BufferedFrame(image.getvalue(), i * 6000, {}, 40, 20, None, "image/png")
                  for i in range(5)]
        labels = []
        text = ImageDraw.ImageDraw.text

        def record(draw, xy, value, *args, **kwargs):
            labels.append((xy, value))
            return text(draw, xy, value, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", record):
            result = contact_sheet(frames, [image.getvalue()] * 5)
        with Image.open(BytesIO(result)) as sheet:
            self.assertEqual(sheet.size, (1200, 420))
            self.assertEqual(sheet.getpixel((150, 90)), (255, 0, 0))
            self.assertEqual(sheet.getpixel((150, 300)), (255, 0, 0))
        self.assertEqual(labels, [((8, 185), "1 · 0:00"), ((308, 185), "2 · 0:06"),
                                  ((608, 185), "3 · 0:12"), ((908, 185), "4 · 0:18"),
                                  ((8, 395), "5 · 0:24")])
        self.assertIsNone(contact_sheet([], []))
