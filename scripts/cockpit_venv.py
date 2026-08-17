"""Keep a cockpit checkout's installed environment matched to its tree.

A fast-forwarded clone is not an installed environment. Deploying v0.32.0
left the cockpit ``.venv`` without Pillow; the restart timer fired, killed
the old generation, and the replacement died in three seconds on
``import PIL``. A later probe that only asked ``import partyline.server``
passed while the cockpit interpreter loaded the *workbench* via an
editable ``.pth`` — importability is not identity.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

Command = Callable[..., subprocess.CompletedProcess[str]]
IDENTITY = (
    "import json, partyline; "
    "print(json.dumps({'file': partyline.__file__, 'version': partyline.__version__}))"
)
VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)


def sync_env(cockpit: Path) -> dict[str, str]:
    """Pin VIRTUAL_ENV to this cockpit so uv cannot follow another checkout."""
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    venv = cockpit / ".venv"
    if venv.is_dir():
        env["VIRTUAL_ENV"] = str(venv.resolve())
    return env


def sync_locked(
    cockpit: Path, *, run: Command = subprocess.run
) -> tuple[str, str] | None:
    """Install the lockfile into the cockpit venv. None means it matches."""
    completed = run(
        ["uv", "sync", "--locked", "--project", str(cockpit)],
        cwd=cockpit,
        env=sync_env(cockpit),
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "uv sync failed").strip()
        return (
            f"the cockpit venv is not installed from its lockfile: {detail}",
            "run `uv sync --locked` in the cockpit clone; do not restart until it boots",
        )
    return None


def tree_version(cockpit: Path) -> str | None:
    try:
        text = (cockpit / "partyline" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return None
    found = VERSION_RE.search(text)
    return found.group(1) if found else None


def loaded_from_cockpit(loaded: Path, cockpit: Path) -> bool:
    root = cockpit.resolve()
    file = loaded.resolve()
    return root == file or root in file.parents


def probe_server(
    python: Path, cockpit: Path, *, run: Command = subprocess.run
) -> str | None:
    """Refuse unless this interpreter loads *this* cockpit's partyline."""
    completed = run(
        # -P: cwd must not shadow a poisoned editable .pth. Today's cockpit
        # venv had one pointing at the workbench; importing from the cockpit
        # directory made sys.path[0] hide it and the probe went green.
        [str(python), "-P", "-c", IDENTITY],
        cwd=cockpit,
        env=sync_env(cockpit),
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        return (completed.stderr or completed.stdout or "import partyline.server failed").strip()
    try:
        info = json.loads(completed.stdout)
        loaded = Path(info["file"])
        version = str(info["version"])
    except (json.JSONDecodeError, KeyError, TypeError, OSError):
        return "interpreter did not report partyline file and version"
    if not loaded_from_cockpit(loaded, cockpit):
        return f"interpreter loaded {loaded}, not the cockpit at {cockpit.resolve()}"
    expected = tree_version(cockpit)
    if expected is None:
        return f"could not read __version__ from {cockpit / 'partyline' / '__init__.py'}"
    if version != expected:
        return f"interpreter reports {version}, cockpit tree is {expected}"
    return None


def replacement_python(server: Path) -> Path:
    """The venv interpreter that sits next to the console script."""
    return server.parent / "python3"


def cockpit_can_boot(
    cockpit: Path, *, required: bool = False, run: Command = subprocess.run
) -> tuple[str, str] | None:
    """Refuse a cockpit whose interpreter is not this tree, bootable."""
    python = cockpit / ".venv" / "bin" / "python3"
    if not python.is_file():
        if not required:
            return None
        return (
            f"the cockpit Python is missing at {python}",
            "run `uv sync --locked` in the cockpit clone; do not restart until it boots",
        )
    if error := probe_server(python, cockpit, run=run):
        return (
            f"the cockpit interpreter cannot boot this tree: {error}",
            "run `uv sync --locked` in the cockpit clone; do not restart until it boots",
        )
    return None
