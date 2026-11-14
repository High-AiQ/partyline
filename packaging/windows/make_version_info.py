"""Write the Windows version resource the frozen exe carries: `python make_version_info.py OUT.txt`.

PyInstaller's `version=` takes this file; Properties -> Details then shows the helper version. The number is
read from partyline_helper/__init__.py, the same source as the installer's file name and the release tag.
"""
import re
import sys
from pathlib import Path

from partyline_helper import __version__


def four_part(version):
    """1.2.0 -> (1, 2, 0, 0): Windows version resources have exactly four numbers."""
    parts = [int(part) for part in re.findall(r"\d+", version)][:4]
    return tuple(parts + [0] * (4 - len(parts)))


def version_info(version=__version__):
    numbers = four_part(version)
    strings = [("CompanyName", "Partyline"), ("FileDescription", "Partyline Helper"),
               ("FileVersion", version), ("InternalName", "PartylineHelper"),
               ("OriginalFilename", "PartylineHelper.exe"), ("ProductName", "Partyline Helper"),
               ("ProductVersion", version)]
    rows = ",\n          ".join(f"StringStruct('{key}', '{value}')" for key, value in strings)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
          {rows}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv):
    out = Path(argv[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(version_info(), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
