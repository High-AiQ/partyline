"""Parsing for the pinned `--log-file` of an Antigravity (`agy`) attachment.

The log records every accepted submission at submit time — minutes before
the transcript catches up — as glog lines carrying
``HandleUserInput called with text: "..."``. The payload is Go-quoted, so
digests with real newlines appear with literal ``\\n`` sequences; both sides
must be unescaped and whitespace-normalized before containment can judge.
Glog timestamps are month-day, local, and yearless; a line whose timestamp
cannot be parsed cannot judge anything.
"""

from __future__ import annotations

import re
import time

SUBMITTED = re.compile(r'HandleUserInput called with text: "(.*)"')
GLOG_TS = re.compile(r"\b[IWEF](\d{2})(\d{2}) (\d{2}):(\d{2}):(\d{2})")

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unquote(text: str) -> str:
    """Undo the Go quoting the log applies to a submission (`\\n`, `\\t` …)."""
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(0)), text)


def _glog_timestamp(line: str) -> float | None:
    """Parse a glog prefix (`I0822 08:43:45`) — month-day, local, yearless."""
    match = GLOG_TS.search(line)
    if not match:
        return None
    month, day, hour, minute, second = (int(group) for group in match.groups())
    year = time.localtime().tm_year
    stamp = time.mktime((year, month, day, hour, minute, second, 0, 0, -1))
    if stamp > time.time() + 86400:
        # The year is unstated: a stamp in the future is last year's line.
        stamp = time.mktime((year - 1, month, day, hour, minute, second, 0, 0, -1))
    return stamp


def submission(line: str) -> tuple[str, float] | None:
    """The submitted text and when, from a log line — or None if the line is
    not a submission or its timestamp is unparseable (it cannot judge)."""
    match = SUBMITTED.search(line)
    if not match:
        return None
    stamp = _glog_timestamp(line)
    if stamp is None:
        return None
    return _unquote(match.group(1)), stamp
