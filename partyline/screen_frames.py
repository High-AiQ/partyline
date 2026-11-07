"""In-memory bounded frame selection shared by composer and screen_frame."""

import asyncio
from dataclasses import dataclass, field

from .screen_protocol import FRAME_BUFFER_SIZE


@dataclass
class BufferedFrame:
    data: bytes
    ts_ms: int
    region: dict
    out_width: int
    out_height: int
    pointer: dict | None
    mime: str
    sequence: int = 0


@dataclass
class ShareBuffer:
    share_id: str
    conv_id: str
    device_id: str
    owner_id: int
    requested_by: str
    region: dict
    status: str = "waiting"
    frames: list[BufferedFrame] = field(default_factory=list)
    last_message_ts: dict[str, int] = field(default_factory=dict)
    attached: dict[str, set[int]] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    agent_frames: dict = field(default_factory=dict)
    frame_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_sequence: int = 0

    def add(self, frame: BufferedFrame) -> None:
        self.next_sequence += 1
        frame.sequence = self.next_sequence
        self.frames.append(frame)
        del self.frames[:-FRAME_BUFFER_SIZE]
        live = {item.sequence for item in self.frames}
        for seen in self.attached.values():
            seen.intersection_update(live)


def frames_since(share: ShareBuffer, timestamp_ms: int) -> list[BufferedFrame]:
    return [frame for frame in share.frames if frame.ts_ms > timestamp_ms]


def pick_distinct(frames: list[BufferedFrame], count: int = 3) -> list[BufferedFrame]:
    """Pick the latest requested count while preserving oldest-first delivery.

    Helper-side change gating makes almost all adjacent frames distinct; this
    still removes duplicates byte-for-byte as a defensive selection boundary.
    """
    distinct = []
    seen = set()
    for frame in reversed(frames):
        if frame.data in seen:
            continue
        seen.add(frame.data)
        distinct.append(frame)
        if len(distinct) >= count:
            break
    return list(reversed(distinct)) if count > 0 else []
