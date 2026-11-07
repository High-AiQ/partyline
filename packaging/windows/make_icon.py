"""Write the multi-size .ico used by the exe and the installer: `python make_icon.py OUT.ico`.

Drawn from the tray's own artwork so there is no binary asset to keep in git.
"""
import sys
from pathlib import Path

from partyline_helper.tray import draw_icon

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main(argv):
    out = Path(argv[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    draw_icon("paired", 256).save(out, format="ICO", sizes=SIZES)


if __name__ == "__main__":
    main(sys.argv[1:])
