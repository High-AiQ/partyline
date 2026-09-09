"""Read this attachment's `--log-file` for the conversation the CLI created.

`agy` accepts no caller-chosen id. The only structured identity it emits is a
``Created conversation <uuid>`` line on the log Partyline pinned for this
attachment. Resume used to skip that and tail ``cli_session`` — so when the
CLI opened a new conversation, the nonce and clearance landed in a file the
adapter never opened.

Discovery never scans the brain directory. It reads only this attachment's
log, and on resume only bytes written after the activation marked the file,
so a prior ``Created conversation`` line cannot pin the old transcript.
"""

from __future__ import annotations

import re
from pathlib import Path

CREATED = re.compile(r"Created conversation ([0-9a-fA-F-]{36})")

LogMark = tuple[int, int]


def log_mark(path: Path) -> LogMark:
    """Size and inode before this activation may write. Missing file is (0, 0)."""
    try:
        info = path.stat()
    except OSError:
        return (0, 0)
    return (info.st_size, info.st_ino)


def suffix_offset(path: Path, mark: LogMark) -> int:
    """Byte offset of this activation's writes, or 0 if the log was replaced.

    A truncated or replaced file can be shorter than the remembered offset;
    seeking there would skip a new ``Created conversation`` at the start.
    """
    size, inode = mark
    try:
        info = path.stat()
    except OSError:
        return 0
    if info.st_ino != inode or info.st_size < size:
        return 0
    return size


def conversation_from_log(path: Path, *, after: int = 0) -> str | None:
    """The last Created-conversation id in this log, optionally after `after`.

    Last-wins so a resume that appends a new id is not stuck on the first.
    """
    try:
        with path.open("rb") as file:
            if after:
                file.seek(after)
            text = file.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    ids = CREATED.findall(text)
    return ids[-1] if ids else None
