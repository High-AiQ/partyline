"""A bounded tail of a process's raw pty output, for explaining early exits."""

import re

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\-_])")


class OutputTail:
    def __init__(self, limit: int = 4096):
        self._limit = limit
        self._raw = b""

    def feed(self, data: bytes) -> None:
        self._raw = (self._raw + data)[-self._limit:]

    def lines(self, count: int) -> list[str]:
        """The last ``count`` non-blank lines, escapes stripped."""
        text = _ANSI.sub("", self._raw.decode("utf-8", "replace")).replace("\r\n", "\n")
        # A bare carriage return redraws a line: only its final state matters.
        rows = [row.rsplit("\r", 1)[-1].rstrip() for row in text.split("\n")]
        return [row for row in rows if row.strip()][-count:]
