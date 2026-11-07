"""Compact, numbered overview of the frames in a walkthrough."""

from io import BytesIO
from math import ceil

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .screen_frames import BufferedFrame

COLUMNS = 4
TILE_WIDTH = 300
IMAGE_HEIGHT = 180
LABEL_HEIGHT = 30


def contact_sheet(frames: list[BufferedFrame], images: list[bytes]) -> bytes | None:
    """Render prepared frame images in timeline order, or nothing for an empty take."""
    if not frames:
        return None
    columns = min(COLUMNS, len(frames))
    rows = ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * TILE_WIDTH, rows * (IMAGE_HEIGHT + LABEL_HEIGHT)), "#20242a")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for index, (frame, data) in enumerate(zip(frames, images, strict=True)):
        x = index % columns * TILE_WIDTH
        y = index // columns * (IMAGE_HEIGHT + LABEL_HEIGHT)
        with Image.open(BytesIO(data)) as source:
            tile = ImageOps.contain(source.convert("RGB"), (TILE_WIDTH, IMAGE_HEIGHT))
        sheet.paste(tile, (x + (TILE_WIDTH - tile.width) // 2, y + (IMAGE_HEIGHT - tile.height) // 2))
        seconds = frame.ts_ms // 1000
        draw.text((x + 8, y + IMAGE_HEIGHT + 5),
                  f"{index + 1} · {seconds // 60}:{seconds % 60:02d}", font=font, fill="white")
    output = BytesIO()
    sheet.save(output, format="PNG")
    return output.getvalue()
