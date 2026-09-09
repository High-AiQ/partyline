"""Read this attachment's `--log-file` for the conversation the CLI created.

`agy` accepts no caller-chosen id. The only structured identity it emits is a
``Created conversation <uuid>`` or ``Resuming conversation <uuid>`` line on the
log Partyline pinned for this attachment. Resume used to skip that and tail
``cli_session`` — so when the CLI opened a new conversation, the nonce and
clearance landed in a file the adapter never opened.

Both verbs matter, and reading only one was its own outage: ``build_command``
passes ``--conversation`` on resume, so a resumed CLI says "Resuming" and never
"Created". Discovery that recognised creation alone therefore worked for the
run that created the conversation and failed on every restart after it, leaving
a live process nobody was listening to.

Discovery never scans the brain directory. It reads only this attachment's
log, and on resume only bytes written after the activation marked the file,
so a prior ``Created conversation`` line cannot pin the old transcript.
"""

from __future__ import annotations

import re
from pathlib import Path

# The CLI announces which conversation it is on with two different verbs, and
# which one it uses is decided by us: `build_command` passes `--conversation`
# on resume, so a resumed activation only ever says "Resuming". Matching
# "Created" alone meant discovery could succeed exactly once — the run that
# created the conversation — and then never again for that attachment.
CONVERSATION = re.compile(r"(?:Created|Resuming) conversation ([0-9a-fA-F-]{36})")

# The CLI echoes whatever was typed at it back into this same log:
# ``input_loop.go: HandleUserInput called with text: "…"``. That text is chat
# anyone on the line can write, so without this an ordinary message could name
# a conversation and pin the adapter to a transcript of the sender's choosing.
# Observed in the wild already — a message discussing this very bug contained
# the phrase, and was harmless only because no uuid followed it.
ECHOED_INPUT = "HandleUserInput called with text:"

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
    """The conversation this activation says it is on, optionally after `after`.

    Last-wins so a resume that appends a new id is not stuck on the first.
    Lines that are the CLI quoting its own input back are skipped: they carry
    chat text, and chat text is not evidence about which conversation the CLI
    opened.
    """
    try:
        with path.open("rb") as file:
            if after:
                file.seek(after)
            text = file.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    found = None
    for line in text.splitlines():
        if ECHOED_INPUT in line:
            continue
        if match := CONVERSATION.findall(line):
            found = match[-1]
    return found
