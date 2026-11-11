# PyInstaller spec for the Windows helper. Run from the repository root:
#   uv run --locked --extra helper --with pyinstaller==6.14.2 pyinstaller packaging/windows/PartylineHelper.spec
# Onedir + windowed: no console, no per-launch unpacking (onefile would extract ~60 MB to %TEMP% on every
# start, including every consent dialog, and trips antivirus heuristics more often).
import os

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821 - SPECPATH is set by PyInstaller
ICON = os.environ.get("HELPER_ICON") or os.path.join(ROOT, "build", "PartylineHelper.ico")

# Capture, input, tray and border backends are chosen at runtime, so import them all explicitly.
hidden = (collect_submodules("partyline_helper") + collect_submodules("pynput")
          + collect_submodules("pystray") + collect_submodules("windows_capture"))

a = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "entry.py")],
    pathex=[ROOT],
    datas=copy_metadata("partyline"),  # importlib.metadata.version("partyline") is the version we report
    hiddenimports=hidden,
    excludes=["pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="PartylineHelper",
    console=False,  # windowed: nothing flashes, and stdout/stderr are None (all feedback is a dialog)
    icon=ICON if os.path.exists(ICON) else None,
    uac_admin=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PartylineHelper")
