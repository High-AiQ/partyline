"""Which checkout the running process serves from — what a restart would deploy.

A captain once pulled ~/code/partyline while the service ran from
~/partyline-lan-cockpit, filed a restart, and a restart deployed nothing: the
running process's own checkout had never moved, and nothing said so. This
module captures the served path and its HEAD once, when the process starts, so
``/api/version`` can name the served checkout and a restart request can tell
"nothing changed since this process started" — refused as nothing to deploy —
from "the checkout moved: this restart deploys the pull".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent
_GIT_TIMEOUT = 10


def _git(path: str | None, *args: str) -> str | None:
    directory = str(Path(path)) if path else str(_PACKAGE)
    try:
        done = subprocess.run(
            ["git", "-C", directory, *args], capture_output=True, text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def checkout_path(path: str | None = None) -> str | None:
    """The repository root the given path lives in (default: the partyline package)."""
    return _git(path, "rev-parse", "--show-toplevel")


def git_head(path: str | None = None) -> str | None:
    """HEAD's commit in the given checkout (default: the partyline package's)."""
    return _git(path, "rev-parse", "HEAD")


_STARTUP_PATH = checkout_path()
_STARTUP_HEAD = git_head()


def startup_path() -> str | None:
    """The checkout the running process was started from, captured at import."""
    return _STARTUP_PATH


def startup_head() -> str | None:
    """The commit the running process was started on, captured at import."""
    return _STARTUP_HEAD
