"""Fan-out state for live terminal viewers."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass


VIEWER_QUEUE_LIMIT = 32


@dataclass(frozen=True)
class TerminalViewer:
    queue: asyncio.Queue[bytes | None]
    snapshot: str


class TerminalViewerRegistry:
    """Subscribers receive a coherent snapshot followed by live bytes.

    Clients send UTF-8 text WebSocket frames; the server sends binary pty frames.
    """

    def __init__(self, snapshot: Callable[[], str]):
        self._snapshot = snapshot
        self._queues: set[asyncio.Queue[bytes | None]] = set()
        self._closed = False

    def attach(self) -> TerminalViewer:
        """Snapshot and subscribe atomically from the event loop's viewpoint."""
        snapshot = self._snapshot()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=VIEWER_QUEUE_LIMIT)
        if self._closed:
            queue.put_nowait(None)
        else:
            self._queues.add(queue)
        return TerminalViewer(queue, snapshot)

    def detach(self, viewer: TerminalViewer) -> None:
        self._queues.discard(viewer.queue)

    def publish(self, data: bytes) -> None:
        for queue in tuple(self._queues):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self._queues.discard(queue)
                continue
            queue.put_nowait(data)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for queue in tuple(self._queues):
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)
        self._queues.clear()
