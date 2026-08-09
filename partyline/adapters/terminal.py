"""Small terminal-control replies needed by full-screen process adapters."""

from __future__ import annotations

import pyte


FOREGROUND = b"rgb:0000/0000/0000"
BACKGROUND = b"rgb:ffff/ffff/ffff"
MAX_QUERY_TAIL = 128
KEYS = {
    "enter": b"\r", "esc": b"\x1b", "tab": b"\t", "space": b" ",
    "up": b"\x1b[A", "down": b"\x1b[B", "left": b"\x1b[D", "right": b"\x1b[C",
    "y": b"y", "n": b"n", "1": b"1", "2": b"2", "3": b"3", "4": b"4",
}


def terminal_responses(screen: pyte.Screen, tail: bytes, data: bytes) -> tuple[bytes, bytes]:
    """Return replies and an unfinished control-sequence tail from PTY output.

    A PTY is not a terminal emulator: applications write DSR/DA/OSC queries to
    it, then expect replies on stdin.  Keep incomplete queries across reads so
    a split escape sequence cannot leave a full-screen application waiting.
    """
    stream = tail + data
    replies = bytearray()
    cursor = 0
    while (start := stream.find(b"\x1b", cursor)) != -1:
        if start + 1 == len(stream):
            return bytes(replies), stream[start:]
        kind = stream[start + 1:start + 2]
        if kind == b"[":
            end = _csi_end(stream, start + 2)
            if end is None:
                return bytes(replies), stream[start:][-MAX_QUERY_TAIL:]
            params = stream[start + 2:end]
            final = stream[end:end + 1]
            if final == b"n" and params == b"6":
                replies.extend(f"\x1b[{screen.cursor.y + 1};{screen.cursor.x + 1}R".encode())
            elif final == b"c" and params in (b"", b"0"):
                replies.extend(b"\x1b[?62c")
            cursor = end + 1
        elif kind == b"]":
            end, terminator = _osc_end(stream, start + 2)
            if end is None:
                return bytes(replies), stream[start:][-MAX_QUERY_TAIL:]
            query = stream[start + 2:end]
            if query == b"10;?":
                replies.extend(b"\x1b]10;" + FOREGROUND + terminator)
            elif query == b"11;?":
                replies.extend(b"\x1b]11;" + BACKGROUND + terminator)
            cursor = end + len(terminator)
        else:
            cursor = start + 2
    return bytes(replies), b""


def screen_text(screen: pyte.Screen) -> str:
    """Return the populated portion of a pyte screen."""
    lines = [line.rstrip() for line in screen.display]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _csi_end(stream: bytes, start: int) -> int | None:
    for index in range(start, len(stream)):
        if 0x40 <= stream[index] <= 0x7E:
            return index
    return None


def _osc_end(stream: bytes, start: int) -> tuple[int | None, bytes]:
    for index in range(start, len(stream)):
        if stream[index:index + 1] == b"\x07":
            return index, b"\x07"
        if stream[index:index + 2] == b"\x1b\\":
            return index, b"\x1b\\"
    return None, b""
