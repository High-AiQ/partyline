"""Queue for messages arriving mid-turn for receipt-capable adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class DeliveryQueue:
    """Manages held mention deliveries while an attachment's turn is open."""

    def __init__(self) -> None:
        self._held: dict[str, list[dict]] = {}
        self._deliver_fns: dict[str, Callable[[list[dict]], Awaitable[None]]] = {}
        self._post_fns: dict[str, Callable[..., Awaitable[None]]] = {}

    def register_deliver(
        self,
        att_id: str,
        deliver_fn: Callable[[list[dict]], Awaitable[None]],
        post_fn: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._deliver_fns[att_id] = deliver_fn
        if post_fn is not None:
            self._post_fns[att_id] = post_fn

    def unregister(self, att_id: str) -> None:
        self._held.pop(att_id, None)
        self._deliver_fns.pop(att_id, None)
        self._post_fns.pop(att_id, None)

    def held_count(self, att_id: str) -> int:
        return len(self._held.get(att_id, []))

    def enqueue(self, att_id: str, messages: list[dict]) -> int:
        """Enqueue messages for an attachment mid-turn, deduplicating by id."""
        current = self._held.setdefault(att_id, [])
        existing_ids = {m.get("id") for m in current if m.get("id") is not None}
        for msg in messages:
            msg_id = msg.get("id")
            if msg_id is None or msg_id not in existing_ids:
                current.append(msg)
                if msg_id is not None:
                    existing_ids.add(msg_id)
        return len(current)

    async def flush(self, att_id: str) -> list[dict]:
        """Drain and deliver all held messages for an attachment on turn end."""
        messages = self._held.pop(att_id, [])
        if messages and att_id in self._deliver_fns:
            await self._deliver_fns[att_id](messages)
        return messages

    async def discard_on_exit(self, att_id: str, name: str, status: str) -> list[dict]:
        """Discard held messages on process exit/detach and emit notice if any."""
        messages = self._held.pop(att_id, [])
        if messages and att_id in self._post_fns:
            count = len(messages)
            plural = "mention" if count == 1 else "mentions"
            await self._post_fns[att_id](
                "system",
                "system",
                f"⚠ @{name} {status} with {count} held {plural} undelivered",
            )
        return messages
