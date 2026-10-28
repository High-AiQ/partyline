"""Bounded raw terminal history, with conservative truncation boundaries."""

import os
from weakref import WeakSet

DEFAULT_REPLAY_BYTES = 256 * 1024
MAX_REPLAY_BYTES = 1024 * 1024
TOTAL_REPLAY_BYTES = 64 * 1024 * 1024
_rings: WeakSet = WeakSet()


def replay_limit() -> int:
    try:
        return max(0, min(MAX_REPLAY_BYTES, int(os.getenv(
            "PARTYLINE_TERMINAL_REPLAY_BYTES", str(DEFAULT_REPLAY_BYTES)))))
    except ValueError:
        return DEFAULT_REPLAY_BYTES


class RawReplay:
    def __init__(self, limit: int):
        available = TOTAL_REPLAY_BYTES - sum(ring.limit for ring in _rings)
        self.limit = limit if limit <= available else 0
        self.available = limit == 0 or self.limit > 0
        _rings.add(self)
        self.data = bytearray()
        self.state = "ground"
        self.utf = 0
        self.truncated = False

    def _discard(self, byte: int) -> None:
        if self.state == "string_escape":
            self.state = "ground" if byte == 0x5c else "string"
        elif self.state == "string":
            if byte == 0x07:
                self.state = "ground"
            elif byte == 0x1b:
                self.state = "string_escape"
        elif self.state == "csi":
            if 0x40 <= byte <= 0x7e:
                self.state = "ground"
            elif byte == 0x1b:
                self.state = "escape"
        elif self.state == "escape":
            if byte == 0x5b:
                self.state = "csi"
            elif byte in (0x5d, 0x50, 0x58, 0x5e, 0x5f):
                self.state = "string"
            elif not 0x20 <= byte <= 0x2f:
                self.state = "ground"
        elif self.utf and 0x80 <= byte <= 0xbf:
            self.utf -= 1
        else:
            self.utf = 0
            if byte == 0x1b:
                self.state = "escape"
            elif 0xc2 <= byte <= 0xdf:
                self.utf = 1
            elif 0xe0 <= byte <= 0xef:
                self.utf = 2
            elif 0xf0 <= byte <= 0xf4:
                self.utf = 3

    def append(self, data: bytes) -> None:
        self.data.extend(data)
        excess = max(0, len(self.data) - self.limit)
        if excess:
            self.truncated = True
        index = 0
        while index < len(self.data) and (
            index < excess or (self.truncated and (self.state != "ground" or self.utf))
        ):
            self._discard(self.data[index])
            index += 1
        if index:
            del self.data[:index]

    def copy(self) -> bytes:
        return bytes(self.data)
