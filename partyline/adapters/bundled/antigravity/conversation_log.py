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

# Bytes remembered at the end of the pre-spawn log. Same-inode truncate then
# rewrite past the old size keeps inode and size-gte; this tail must still match.
TAIL = 64
LogMark = tuple[int, int, bytes]


def log_mark(path: Path) -> LogMark:
    """Size, inode, and end bytes before this activation may write."""
    try:
        info = path.stat()
    except OSError:
        return (0, 0, b"")
    length = min(TAIL, info.st_size)
    try:
        with path.open("rb") as file:
            if info.st_size > length:
                file.seek(info.st_size - length)
            tail = file.read(length)
    except OSError:
        return (0, 0, b"")
    return (info.st_size, info.st_ino, tail)


def suffix_offset(path: Path, mark: LogMark) -> int:
    """Byte offset of this activation's writes, or 0 if the log was rewritten.

    Shorter size or a new inode is the obvious replacement. The CLI can also
    truncate the same inode and write past the old size before we poll: inode
    and size both look fine, but the remembered tail at that boundary will
    not match, so the offset resets rather than hiding a new Created line.
    """
    size, inode, tail = mark
    try:
        info = path.stat()
    except OSError:
        return 0
    if info.st_ino != inode or info.st_size < size:
        return 0
    if size == 0:
        return 0
    try:
        with path.open("rb") as file:
            file.seek(size - len(tail))
            current = file.read(len(tail))
    except OSError:
        return 0
    if current != tail:
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
