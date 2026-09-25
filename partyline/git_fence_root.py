"""Private overlay for root-level files in a shared Git directory."""

from __future__ import annotations

import os
import shutil
import tempfile


_EXCLUDES = {"config", "hooks", "objects", "packed-refs", "refs", "logs", "worktrees"}


def _ensure_directory(path: str) -> None:
    if os.path.islink(path) or (os.path.lexists(path) and not os.path.isdir(path)):
        os.unlink(path)
    os.makedirs(path, exist_ok=True)


def _copy_file(source: str, mirror: str, name: str) -> None:
    target = os.path.join(mirror, name)
    parent = os.path.dirname(target)
    _ensure_directory(parent)
    fd, temporary = tempfile.mkstemp(dir=parent)
    os.close(fd)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh(common: str, mirror: str) -> None:
    """Copy current root-level Git files into the line's private overlay."""
    _ensure_directory(mirror)
    for name in os.listdir(common):
        if name in _EXCLUDES:
            continue
        source = os.path.join(common, name)
        if os.path.isfile(source) and not os.path.islink(source):
            _copy_file(source, mirror, name)
        elif name in {"branches", "info"} and os.path.isdir(source):
            for base, dirs, files in os.walk(source, followlinks=False):
                dirs[:] = [item for item in dirs
                           if not os.path.islink(os.path.join(base, item))]
                relative = os.path.relpath(base, common)
                _ensure_directory(os.path.join(mirror, relative))
                for filename in files:
                    source_file = os.path.join(base, filename)
                    if os.path.isfile(source_file) and not os.path.islink(source_file):
                        relative_file = os.path.relpath(source_file, common)
                        _copy_file(source_file, mirror, relative_file)
