"""Exact-message queue for receipt-capable adapters' deferred deliveries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class DeliveryQueue:
    """Hold mid-turn digests and durable batches a CLI proved it skipped."""

    def __init__(self) -> None:
        self._held: dict[str, set[int]] = {}
        self._compact_fns: dict[str, Callable[[], Awaitable[None]]] = {}
        self._persisted_fns: dict[str, Callable[[], list[int]]] = {}
        self._persist_fns: dict[str, Callable[[list[int]], Awaitable[bool]]] = {}
        self._flush_fns: dict[str, Callable[[list[int]], Awaitable[bool]]] = {}
        self._post_fns: dict[str, Callable[..., Awaitable[None]]] = {}

    def register_deliver(
        self,
        att_id: str,
        flush_fn: Callable[[list[int]], Awaitable[bool]] | None = None,
        post_fn: Callable[..., Awaitable[None]] | None = None,
        persisted_fn: Callable[[], list[int]] | None = None,
        persist_fn: Callable[[list[int]], Awaitable[bool]] | None = None,
    ) -> None:
        if flush_fn is not None:
            self._flush_fns[att_id] = flush_fn
        if persisted_fn is not None:
            self._persisted_fns[att_id] = persisted_fn
        if persist_fn is not None:
            self._persist_fns[att_id] = persist_fn
        if post_fn is not None:
            self._post_fns[att_id] = post_fn

    def unregister(self, att_id: str) -> None:
        self._held.pop(att_id, None)
        self._compact_fns.pop(att_id, None)
        self._flush_fns.pop(att_id, None)
        self._persisted_fns.pop(att_id, None)
        self._persist_fns.pop(att_id, None)
        self._post_fns.pop(att_id, None)

    def held_ids(self, att_id: str) -> list[int]:
        ids = set(self._held.get(att_id, ()))
        if persisted := self._persisted_fns.get(att_id):
            ids.update(persisted())
        return sorted(ids)

    def held_count(self, att_id: str) -> int:
        return len(self.held_ids(att_id))

    def hold(self, att_id: str, messages: list[dict]) -> int:
        """Hold this normal full digest by id; later chatter is not included."""
        held = self._held.setdefault(att_id, set())
        held.update(message["id"] for message in messages if isinstance(message.get("id"), int))
        return self.held_count(att_id)

    async def repool(
        self,
        att_id: str,
        message_ids: list[int],
        is_working: Callable[[], bool],
        announce: Callable[[], Awaitable[None]],
    ) -> bool:
        """Persist a skipped batch, then flush now if the attachment is idle."""
        persist = self._persist_fns.get(att_id)
        if persist is None or not await persist(message_ids):
            return False
        if is_working():
            await announce()
        else:
            await self.flush(att_id)
        return True

    async def flush(self, att_id: str, *, turn_ended: bool = False) -> bool:
        """Deliver only the ordered union that caused or survived deferral."""
        if turn_ended and (compact := self._compact_fns.get(att_id)):
            await compact()
            self._compact_fns.pop(att_id, None)
            return True
        message_ids = self.held_ids(att_id)
        if not message_ids:
            return False
        flush = self._flush_fns.get(att_id)
        if flush is None:
            return False
        delivered = await flush(message_ids)
        if delivered:
            held = self._held.get(att_id)
            if held is not None:
                held.difference_update(message_ids)
                if not held:
                    self._held.pop(att_id, None)
        return delivered

    async def compact(
        self, att_id: str, send: Callable[[], Awaitable[None]], working: bool
    ) -> bool:
        """Paste now while idle, or keep one latest-wins slot for turn end."""
        if working:
            self._compact_fns[att_id] = send
            return True
        await send()
        return False

    async def discard_on_exit(self, att_id: str, name: str, status: str) -> int:
        """Discard held messages on process exit/detach and emit notice if any."""
        self._compact_fns.pop(att_id, None)
        count = len(self._held.pop(att_id, ()))
        if count and att_id in self._post_fns:
            plural = "mention" if count == 1 else "mentions"
            await self._post_fns[att_id](
                "system",
                "system",
                f"⚠ @{name} {status} with {count} held {plural} undelivered",
            )
        return count
