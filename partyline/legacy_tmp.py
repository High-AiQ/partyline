"""Reap the pre-2.33 legacy temp locations (finding 5.13).

2.33.0 gave every attachment its own directory, but the old locations kept
growing: ``/tmp/claude-<uid>`` holds one directory per session id — and
Partyline's claude sessions are named by attachment id — while pytest leaves
``pytest-<N>`` runs behind on every invocation. Both filled the shared tmpfs
to EDQUOT twice on 2026-10-13.

Rules, deliberately narrow:

- A claude session directory is removed only when its name is a Partyline
  attachment id whose row is **not** live. Unknown ids may be Greg's own
  claude sessions and are never touched.
- A pytest run directory is removed only when its name is ``pytest-<digits>``
  and it has not been modified for 24 hours. ``pytest-current`` is a symlink
  to the newest run and is never removed; symlinks anywhere in a candidate's
  path refuse the reap, never followed out.

Called on server start and on line close. Returns the bytes it freed, so the
caller can log honestly.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

PYTEST_MAX_AGE_SECONDS = 24 * 60 * 60
PYTEST_RUN = re.compile(r"pytest-\d+\Z")


def claude_root() -> Path:
    return Path(f"/tmp/claude-{os.getuid()}")


def pytest_root() -> Path:
    import pwd

    return Path(f"/tmp/pytest-of-{pwd.getpwuid(os.getuid()).pw_name}")


def _guarded_tree(path: Path) -> Path | None:
    """The directory only if every level is a real directory, no symlinks."""
    probe = path
    while probe != probe.parent:
        if os.path.islink(probe):
            return None
        probe = probe.parent
    if not path.is_dir():
        return None
    return path


def _tree_size(path: Path) -> int:
    total, stack = 0, [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _remove(path: Path) -> int:
    freed = _tree_size(path)
    shutil.rmtree(path, ignore_errors=True)
    return freed


def reap_claude_temp(db, root: Path | None = None) -> int:
    """Remove claude session dirs whose attachment is not live.

    Only ids the database knows are candidates, so Greg's own claude
    sessions — ids Partyline never issued — are left exactly as they are.
    """
    root = root or claude_root()
    if not root.is_dir():
        return 0
    known = {
        row["id"]: row["status"]
        for row in db._exec("SELECT id,status FROM attachments").fetchall()
    }
    freed = 0
    for line_dir in sorted(root.iterdir()):
        if not line_dir.is_dir() or line_dir.is_symlink():
            continue
        for session in sorted(line_dir.iterdir()):
            status = known.get(session.name)
            if status is None or status in ("starting", "running"):
                continue
            if _guarded_tree(session) is None:
                continue
            freed += _remove(session)
    return freed


def reap_pytest_temp(root: Path | None = None,
                     *, now: float | None = None,
                     max_age: float = PYTEST_MAX_AGE_SECONDS) -> int:
    """Remove pytest run dirs older than a day; never ``pytest-current``."""
    root = root or pytest_root()
    if not root.is_dir():
        return 0
    now = now if now is not None else time.time()
    freed = 0
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not PYTEST_RUN.match(entry.name):
            continue
        try:
            if now - entry.stat().st_mtime < max_age:
                continue
        except OSError:
            continue
        if _guarded_tree(entry) is None:
            continue
        freed += _remove(entry)
    return freed


def reap_legacy_temp(db, *, claude: Path | None = None,
                     pytest: Path | None = None) -> dict[str, int]:
    """Reap both legacy locations; the bytes freed per location."""
    return {
        "claude": reap_claude_temp(db, claude),
        "pytest": reap_pytest_temp(pytest),
    }
