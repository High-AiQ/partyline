"""The exact command that starts the helper, and a stable copy when this one is a throwaway uvx cache."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .instance import lock_dir

SPEC = "partyline[helper] @ git+https://github.com/High-AiQ/partyline.git"


def record_path():
    return lock_dir() / "install.json"


def is_ephemeral(prefix=None, env=None, temp=None):
    """True for `uvx` / `uv run --with` environments, which uv may delete at any time."""
    prefix = Path(prefix or sys.prefix).resolve()
    env = os.environ if env is None else env
    parts = [part.lower() for part in prefix.parts]
    if any(part.startswith(("environments-v", "archive-v")) for part in parts) and "uv" in parts:
        return True
    cache = env.get("UV_CACHE_DIR")
    roots = [Path(temp or tempfile.gettempdir()).resolve()] + ([Path(cache).resolve()] if cache else [])
    return any(root == prefix or root in prefix.parents for root in roots)


def windowless(python, windows=None):
    """pythonw.exe next to python.exe, so a login or link launch never opens a console."""
    if not (os.name == "nt" if windows is None else windows):
        return str(python)
    candidate = Path(python).with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else str(python)


def current_launch():
    return [windowless(sys.executable), "-m", "partyline_helper"]


def tool_launch(run=subprocess.run, which=shutil.which, env=None):
    """Install a stable copy with `uv tool install`; return (launch argv, notes). Raises RuntimeError."""
    env = os.environ if env is None else env
    uv = env.get("UV") or which("uv")
    if not uv:
        raise RuntimeError("This helper runs from a temporary uvx cache and uv was not found to install "
                           "a stable copy. Install uv (https://docs.astral.sh/uv/), then run install again.")
    command = [uv, "tool", "install", "--force", SPEC]
    done = run(command, capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError("`uv tool install` failed:\n" + (done.stderr or done.stdout or "").strip()[-800:])
    shown = run([uv, "tool", "dir"], capture_output=True, text=True, check=False)
    if shown.returncode or not shown.stdout.strip():
        raise RuntimeError("`uv tool dir` failed; cannot locate the installed helper")
    environment = Path(shown.stdout.strip()) / "partyline"
    windows = os.name == "nt"
    python = environment / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")
    if not python.exists():
        raise RuntimeError(f"Installed tool has no interpreter at {python}")
    return [windowless(python), "-m", "partyline_helper"], [f"ran: uv tool install --force '{SPEC}'",
                                                             f"stable environment: {environment}"]


def resolve_launch(ephemeral=None, **kwargs):
    if is_ephemeral() if ephemeral is None else ephemeral:
        launch, notes = tool_launch(**kwargs)
        return launch, ["current environment is a temporary uvx cache; installed a stable copy"] + notes
    return current_launch(), [f"using this environment: {sys.executable}"]


def save_record(launch, path=None):
    path = path or record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"launch": launch}))


def recorded_launch(path=None):
    """The command install recorded, else the one running now."""
    try:
        launch = json.loads((path or record_path()).read_text())["launch"]
        if isinstance(launch, list) and launch and all(isinstance(item, str) for item in launch):
            return launch
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return current_launch()
