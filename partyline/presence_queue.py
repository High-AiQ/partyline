"""Queue for messages arriving mid-turn for receipt-capable adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class DeliveryQueue:
    """Manages held mention deliveries while an attachment's turn is open."""

    def __init__(self) -> None:
        self._held: dict[str, int] = {}
        self._count_fns: dict[str, Callable[[], int]] = {}
        self._flush_fns: dict[str, Callable[[], Awaitable[bool]]] = {}
        self._post_fns: dict[str, Callable[..., Awaitable[None]]] = {}

    def register_deliver(
        self,
        att_id: str,
        flush_fn: Callable[[], Awaitable[bool]] | None = None,
        post_fn: Callable[..., Awaitable[None]] | None = None,
        count_fn: Callable[[], int] | None = None,
    ) -> None:
        if flush_fn is not None:
            self._flush_fns[att_id] = flush_fn
        if count_fn is not None:
            self._count_fns[att_id] = count_fn
        if post_fn is not None:
            self._post_fns[att_id] = post_fn

    def unregister(self, att_id: str) -> None:
        self._held.pop(att_id, None)
        self._flush_fns.pop(att_id, None)
        self._count_fns.pop(att_id, None)
        self._post_fns.pop(att_id, None)

    def held_count(self, att_id: str) -> int:
        count_fn = self._count_fns.get(att_id)
        return count_fn() if count_fn is not None else self._held.get(att_id, 0)

    def hold(self, att_id: str, count: int) -> int:
        """Record the durable-cursor backlog size; never copy message bodies."""
        self._held[att_id] = max(self._held.get(att_id, 0), count)
        return self._held[att_id]

    async def flush(self, att_id: str) -> bool:
        """Regenerate and deliver the held digest from its durable cursor."""
        flush = self._flush_fns.get(att_id)
        if flush is None:
            return False
        delivered = await flush()
        if delivered:
            self._held.pop(att_id, None)
        return delivered

    async def discard_on_exit(self, att_id: str, name: str, status: str) -> int:
        """Discard held messages on process exit/detach and emit notice if any."""
        count = self._held.pop(att_id, 0)
        if count and att_id in self._post_fns:
            plural = "mention" if count == 1 else "mentions"
            await self._post_fns[att_id](
                "system",
                "system",
                f"⚠ @{name} {status} with {count} held {plural} undelivered",
            )
        return count
