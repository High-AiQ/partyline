"""Read one live process's identity from ``/proc``, without a shell parser.

Split from `restart_server.py` at its line cap. Every function here answers a
question about a process that is still running, and answers it from the
kernel's own record rather than from anything the process could have rewritten.
"""

from __future__ import annotations

import os
from pathlib import Path


def process_generation(pid: int, proc_root: Path = Path("/proc")) -> str | None:
    """Return Linux ``/proc/<pid>/stat`` field 22 without a shell parser.

    The second field is a parenthesised command and may contain spaces, so a
    naive ``split()[21]`` is not correct.  Fields after the closing parenthesis
    begin at field 3; start time is therefore index 19 of that suffix.
    """
    try:
        stat = (proc_root / str(pid) / "stat").read_text()
        suffix = stat[stat.rindex(")") + 1 :].split()
        start = suffix[19]
    except (OSError, ValueError, IndexError):
        return None
    return start if start.isdigit() else None


def process_environment(pid: int, proc_root: Path = Path("/proc")) -> dict[str, str] | None:
    """Return ``/proc/<pid>/environ`` as a mapping, or None if unreadable.

    The trigger that runs this script lives in a transient systemd unit whose
    environment is systemd's minimal default — no user PATH, so a server
    exec'd from here could not find the CLIs it attaches. The replacement must
    inherit the outgoing server's environment, not the trigger's.
    """
    try:
        raw = (proc_root / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    environment = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        key, separator, value = entry.partition(b"=")
        if not separator or not key:
            continue
        environment[key.decode(errors="surrogateescape")] = value.decode(
            errors="surrogateescape")
    return environment or None


def process_cmdline(pid: int, proc_root: Path = Path("/proc")) -> list[str] | None:
    """Return the exact argument vector from ``/proc/<pid>/cmdline``."""
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    arguments = [
        entry.decode(errors="surrogateescape")
        for entry in raw.split(b"\0")
        if entry
    ]
    return arguments or None


def process_cwd(pid: int, proc_root: Path = Path("/proc")) -> Path | None:
    """The working directory a live process is running in.

    A relative path in that process's environment means relative to this, not
    to whatever directory happens to be reading it.
    """
    try:
        return Path(os.readlink(proc_root / str(pid) / "cwd"))
    except OSError:
        return None
