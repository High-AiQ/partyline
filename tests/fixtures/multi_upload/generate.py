"""Rebuild the deterministic six-image and six-text upload sample."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
CARDS = (
    ("01-card.png", 3000, 2000, (197, 62, 61)),
    ("02-card.jpg", 1200, 2400, (38, 121, 157)),
    ("03-card.png", 2400, 2400, (89, 145, 81)),
    ("04-card.jpg", 4000, 1500, (217, 151, 44)),
    ("05-card.png", 1600, 1200, (112, 83, 150)),
    ("06-card.jpg", 900, 3000, (41, 135, 108)),
)


def make_card(filename: str, width: int, height: int, color: tuple[int, int, int]):
    image = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(image)
    band = max(4, min(width, height) // 24)
    draw.rectangle((band, band, width - band, height - band), outline=(255, 255, 255),
                   width=band)
    label = filename[:2]
    font = ImageFont.load_default(size=max(24, min(width, height) // 3))
    bounds = draw.textbbox((0, 0), label, font=font, stroke_width=1)
    x = (width - (bounds[2] - bounds[0])) // 2
    y = (height - (bounds[3] - bounds[1])) // 2
    draw.text((x, y), label, font=font, fill=(255, 255, 255), stroke_width=1,
              stroke_fill=(20, 20, 20))
    path = ROOT / filename
    if path.suffix == ".png":
        image.save(path, format="PNG", optimize=False, compress_level=9)
    else:
        image.save(path, format="JPEG", quality=88, subsampling=0, optimize=False,
                   progressive=False)


def main():
    for card in CARDS:
        make_card(*card)
    texts = {
        "01-notes.txt": b"Multi upload fixture 01\nReadable UTF-8 text.\n",
        "02-lines.txt": b"first line\nsecond line\nthird line\n",
        "03-crlf.txt": b"Windows line endings\r\nsecond line\r\n",
        "04-nul.txt": b"NUL follows:\x00\x00\nthen text\n",
        "05-trailing.txt": b"Keep this final newline.\n",
        "06-notes.txt": b"Multi upload fixture 06\nOrder matters.\n",
    }
    for filename, content in texts.items():
        (ROOT / filename).write_bytes(content)
    lines = []
    generated = {name for name, *_rest in CARDS} | set(texts)
    for path in sorted(ROOT.iterdir()):
        if path.name in generated:
            data = path.read_bytes()
            dimensions = ""
            if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                with Image.open(path) as image:
                    dimensions = f" {image.width}x{image.height}"
            lines.append(f"{hashlib.sha256(data).hexdigest()}  {len(data)} bytes{dimensions}  {path.name}")
    (ROOT / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
