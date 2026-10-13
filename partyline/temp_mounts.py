"""Where temp directories live and how big they have grown (finding 5.15).

Filesystem types come from ``/proc/self/mountinfo``; directory sizes come
from a time-budgeted walk that never follows symlinks.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

_ESCAPE = re.compile(r"\\([0-7]{3})")


def _unescape(mount_point: str) -> str:
    """mountinfo writes a space, tab or newline in a path as ``\\040``-style octal."""
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), mount_point)


def fstype_of(path: Path | str, mountinfo: str = "/proc/self/mountinfo") -> str | None:
    """The filesystem type of the mount that contains ``path``.

    The path is resolved first, so a symlink (``/var/tmp`` -> ``/tmp``) is
    judged by where it really lands. Picks the entry with the longest matching
    mount point; None when mount information is unavailable.
    """
    target = os.path.realpath(path)
    best_point, best_fstype = "", None
    try:
        with open(mountinfo, encoding="utf-8") as stream:
            for line in stream:
                fields = line.split()
                if "-" not in fields:
                    continue
                cut = fields.index("-")
                if cut + 1 >= len(fields):
                    continue
                mount_point, fstype = _unescape(fields[4]), fields[cut + 1]
                if (target == mount_point
                        or target.startswith(mount_point.rstrip("/") + "/")) \
                        and len(mount_point) >= len(best_point):
                    best_point, best_fstype = mount_point, fstype
    except OSError:
        return None
    return best_fstype


def on_tmpfs(path: Path | str, mountinfo: str = "/proc/self/mountinfo") -> bool:
    """True when ``path`` sits on a tmpfs mount (RAM-backed)."""
    return fstype_of(path, mountinfo) == "tmpfs"


def largest_dir_under(path: Path | str,
                      budget_seconds: float = 1.0) -> tuple[str, int] | None:
    """The direct child of ``path`` holding the most bytes, bounded in time.

    Symlinks are never followed. The budget bounds the walk like
    ``dir_size``; a timeout returns whatever was counted so far, possibly
    None.
    """
    deadline = time.monotonic() + budget_seconds
    sums: dict[str, int] = {}
    stack = [str(path)]
    while stack and time.monotonic() <= deadline:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            size = entry.stat(follow_symlinks=False).st_size
                            sums[current] = sums.get(current, 0) + size
                    except OSError:
                        continue
        except OSError:
            continue
    if not sums:
        return None
    best = max(sums.items(), key=lambda item: item[1])
    return best[0], best[1]
