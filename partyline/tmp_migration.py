"""Clear the previous tmpfs temp root after process temp moved to disk (finding 5.15).

Until 2.36 a process's temp directory lived under ``<gettempdir()>/partyline/<instance>``,
often tmpfs. Once ``base_dir()`` moves to ``/var/tmp`` the old directories are dead weight in
RAM. The sweep is deliberately timid: it never removes a directory a live process still uses
(its cwd, or the ``TMPDIR`` in its environment), because background jobs such as ``nohup``
runs and dev servers survive a Partyline restart with the old paths.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .attachment_tmp import ID_PATTERN, base_dir, dir_size, instance_key

TEMP_VARS = (b"TMPDIR=", b"TMP=", b"TEMP=")


def live_paths(proc: str = "/proc") -> set[str]:
    """Real paths our own live processes sit in or point their temp variables at; best effort."""
    uid, found = os.getuid(), set()
    try:
        names = [name for name in os.listdir(proc) if name.isdigit()]
    except OSError:
        return found
    for name in names:
        base = f"{proc}/{name}"
        try:
            if os.stat(base).st_uid != uid:
                continue
            found.add(os.path.realpath(os.readlink(f"{base}/cwd")))
        except OSError:
            pass
        try:
            with open(f"{base}/environ", "rb") as stream:
                for item in stream.read().split(b"\0"):
                    if item.startswith(TEMP_VARS):
                        found.add(os.path.realpath(item.split(b"=", 1)[1].decode(errors="replace")))
        except OSError:
            continue
    return found


def in_use(entry: Path, live: set[str]) -> bool:
    """True when a live process works in, or points its temp at, ``entry`` or anything under it."""
    real = os.path.realpath(entry)
    return any(path == real or path.startswith(real + os.sep) for path in live)


def reap_previous_tmp_root(db, *, proc: str = "/proc") -> int:
    """Delete the previous temp root's attachment directories; the bytes freed.

    Skips everything when the old root is the same directory as the current one (a symlinked
    ``/var/tmp``, compared by real path), is not ours, or is a symlink; touches only
    ``ID_PATTERN`` names that are real directories; leaves any in use by a live process; and
    removes the old root last, only if it ended up empty.
    """
    old_root = Path(tempfile.gettempdir()) / "partyline" / instance_key()
    if os.path.realpath(old_root) == os.path.realpath(base_dir()):
        return 0
    if old_root.is_symlink() or not old_root.is_dir():
        return 0
    try:
        if os.stat(old_root).st_uid != os.getuid() or os.path.realpath(old_root) != str(old_root):
            return 0
    except OSError:
        return 0
    live, freed = live_paths(proc), 0
    for entry in sorted(old_root.iterdir()):
        if entry.is_symlink() or not ID_PATTERN.match(entry.name) or not entry.is_dir():
            continue
        if os.path.realpath(entry) != str(entry) or in_use(entry, live):
            continue
        size = dir_size(entry, budget=None)
        shutil.rmtree(entry, ignore_errors=True)
        freed += size
    try:
        old_root.rmdir()
    except OSError:
        pass
    return freed
