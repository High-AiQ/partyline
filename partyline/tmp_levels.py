"""Create the directories Partyline owns under a shared temp root, refusing impostors.

``/var/tmp`` is shared and world-writable, so another account could pre-create or symlink
``/var/tmp/partyline`` and have a process's temp land somewhere it controls. Each level
Partyline creates (never the temp root itself) must be a real directory owned by this user;
a level with group or other write is tightened to 0700; anything foreign is refused.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


def private_level(path: Path) -> None:
    """Make ``path`` exist as our own 0700 directory, or raise ``PermissionError`` naming why."""
    if not hasattr(os, "getuid"):
        path.mkdir(mode=0o700, exist_ok=True)
        return
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PermissionError(f"{path} is a symlink or not a directory; refusing to use it as temp space")
    if info.st_uid != os.getuid():
        raise PermissionError(f"{path} is owned by uid {info.st_uid}, not this user; refusing to use it "
                              "as temp space (set PARTYLINE_TMP_BASE to a directory you own)")
    if info.st_mode & 0o022:
        os.chmod(path, 0o700)


def private_levels(root: Path, *levels: str) -> Path:
    """``root`` joined with ``levels``, each created through ``private_level``; ``root`` is only ensured."""
    root.mkdir(parents=True, exist_ok=True)
    path = root
    for level in levels:
        path = path / level
        private_level(path)
    return path
