"""Bounded claim scans over a transcript's head and tail.

A claim token is written when a wake is pasted, which for a resumed session
is at the *end* of an already large file: a long Claude transcript is
dominated by multi-hundred-kilobyte request blobs, so the resumed
activation's token can sit megabytes past the start. Scanning only the head
(the old behaviour) made such a session unclaimable forever. The head still
covers a fresh briefing; the tail covers a resume's first wake.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

# A stranger's multi-megabyte transcript must not be read in full on every poll.
SCAN_BYTES = 512 * 1024


def scan_lines(path: str, limit: int = SCAN_BYTES) -> Iterator[str]:
    """Yield lines from the first and last ``limit`` bytes of ``path``.

    Raises ``OSError`` like ``open``. The head yields whole lines that end
    within ``limit``; the tail starts at the later of ``size - limit`` and
    the end of what the head yielded, so every line is yielded at most once
    and a line the head rejected for crossing the boundary is still seen
    whole whenever it lies in the tail window. Only the partial line at the
    start of a tail window that begins mid-line is dropped.
    """
    with open(path, "rb") as file:
        size = os.fstat(file.fileno()).st_size
        yielded = 0
        for raw in file:
            if yielded + len(raw) > limit:
                break
            yielded += len(raw)
            yield raw.decode("utf-8", errors="replace")
        else:
            return
        start = max(size - limit, yielded)
        if start >= size:
            return
        if start > yielded:
            file.seek(start - 1)
            file.readline()  # the line holding byte start-1, whole or only partly in the window
        else:
            file.seek(start)
        for raw in file:
            yield raw.decode("utf-8", errors="replace")
