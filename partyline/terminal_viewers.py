"""Fan-out state for live terminal viewers."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from . import op_timing
from .terminal_replay import RawReplay, replay_limit


VIEWER_QUEUE_LIMIT = 32


@dataclass(frozen=True)
class TerminalViewer:
    queue: asyncio.Queue[tuple[bytes, float] | None]  # (bytes, enqueue time) or the close sentinel
    snapshot: str
    replay: bytes
    replay_available: bool


class TerminalViewerRegistry:
    """Subscribers receive a coherent snapshot followed by live bytes.

    Clients send UTF-8 text WebSocket frames; the server sends binary pty frames.
    """

    def __init__(self, snapshot: Callable[[], str]):
        self._snapshot = snapshot
        self._replay = RawReplay(replay_limit())
        self._queues: set[asyncio.Queue[tuple[bytes, float] | None]] = set()
        self._closed = False

    def attach(self) -> TerminalViewer:
        """Snapshot and subscribe atomically from the event loop's viewpoint."""
        snapshot = self._snapshot()
        queue: asyncio.Queue[tuple[bytes, float] | None] = asyncio.Queue(maxsize=VIEWER_QUEUE_LIMIT)
        if self._closed:
            queue.put_nowait(None)
        else:
            self._queues.add(queue)
        return TerminalViewer(queue, snapshot, self._replay.copy(), self._replay.available)

    def detach(self, viewer: TerminalViewer) -> None:
        self._queues.discard(viewer.queue)

    def publish(self, data: bytes) -> None:
        self._replay.append(data)
        for queue in tuple(self._queues):
            if queue.full() or len(data) > 65536:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self._queues.discard(queue)
                continue
            queue.put_nowait((data, op_timing.clock()))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for queue in tuple(self._queues):
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)
        self._queues.clear()
