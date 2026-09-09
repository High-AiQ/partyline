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


def log_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


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
