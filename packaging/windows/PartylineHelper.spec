# PyInstaller spec for the Windows helper. Run from the repository root:
#   uv run --locked --extra helper --with pyinstaller==6.14.2 pyinstaller packaging/windows/PartylineHelper.spec
# Onedir + windowed: no console, no per-launch unpacking (onefile would extract ~60 MB to %TEMP% on every
# start, including every consent dialog, and trips antivirus heuristics more often).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821 - SPECPATH is set by PyInstaller
ICON = os.environ.get("HELPER_ICON") or os.path.join(ROOT, "build", "PartylineHelper.ico")
sys.path[:0] = [SPECPATH, ROOT]  # the version script imports partyline_helper from the checkout
from make_version_info import main as write_version_info  # noqa: E402

# Windows version resource (Properties -> Details), always generated here from partyline_helper.__version__ so no
# build path (CI or local) can freeze an exe without it.
VERSION_FILE = os.path.join(ROOT, "build", "version_info.txt")
write_version_info([VERSION_FILE])

# Capture, input, tray and border backends are chosen at runtime, so import them all explicitly.
hidden = (collect_submodules("partyline_helper") + collect_submodules("pynput")
          + collect_submodules("pystray") + collect_submodules("windows_capture"))

a = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "entry.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "partyline_chrome", name), "partyline_helper/chrome_extension")
           for name in ("manifest.json", "worker.js", "relay.js", "attachments.js", "wire.js", "status.js",
                        "refusal.js")],
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
    version=VERSION_FILE,
    uac_admin=False,
)
# Native messaging needs real binary stdin/stdout, unlike the tray executable.
host = Analysis([os.path.join(ROOT, "packaging", "windows", "native_entry.py")], pathex=[ROOT])
host_pyz = PYZ(host.pure)
host_exe = EXE(host_pyz, host.scripts, exclude_binaries=True, name="PartylineChromeHost",
               console=True, version=VERSION_FILE, uac_admin=False)
coll = COLLECT(exe, host_exe, a.binaries, a.datas, host.binaries, host.datas, name="PartylineHelper")
