"""Credit Grok wakes only after its structured transcript records the input."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .transcript import user_input


@dataclass
class PendingWake:
    digest: str
    message_ids: tuple[int, ...]
    after_prompt: int
    confirmed: bool = False


def _matches(content: str, digest: str) -> bool:
    """Match exactly through harmless transcript whitespace reflow."""
    return bool(digest.strip()) and " ".join(digest.split()) == " ".join(content.split())


class WakeReceipts:
    """Ordered pasted wakes and the newest transcript prompt already observed."""

    def __init__(self) -> None:
        self.prompt_index = -1
        self.pending: list[PendingWake] = []
        self._expected_waits: set[tuple[int, ...]] = set()
        self._waiters: dict[tuple[int, ...], asyncio.Event] = {}
        self._results: dict[tuple[int, ...], bool] = {}

    def seed(self, prompt_index: int) -> None:
        self.prompt_index = max(self.prompt_index, prompt_index)

    def expect_wait(self, message_ids: list[int]) -> None:
        self._expected_waits.add(tuple(message_ids))

    async def deliver(self, adapter, messages: list[dict]) -> bool | None:
        message_ids = tuple(
            message["id"] for message in messages if isinstance(message.get("id"), int)
        )
        if message_ids and any(wake.message_ids == message_ids for wake in self.pending):
            return False
        digest = adapter.format_digest(messages)
        if not message_ids:
            if digest.strip():
                await adapter.send_keys(digest)
            adapter._silent_until_wake = False
            return None
        pending = PendingWake(digest, message_ids, self.prompt_index)
        self.pending.append(pending)
        if message_ids in self._expected_waits:
            self._expected_waits.remove(message_ids)
            self._waiters[message_ids] = asyncio.Event()
        try:
            if digest.strip():
                await adapter.send_keys(digest)
        except BaseException:
            self.pending.remove(pending)
            self._waiters.pop(message_ids, None)
            raise
        adapter._silent_until_wake = False
        return False

    async def observe(self, adapter, record: object) -> None:
        parsed = user_input(record)
        if parsed is None:
            return
        prompt_index, content = parsed
        if prompt_index <= self.prompt_index:
            return
        self.prompt_index = prompt_index
        matched_index: int | None = None
        for index, wake in enumerate(self.pending):
            if (
                not wake.confirmed
                and wake.after_prompt < prompt_index
                and _matches(content, wake.digest)
            ):
                wake.confirmed = True
                matched_index = index
                break

        # A later cumulative digest proves an earlier paste was skipped: its
        # structured user record arrived first, and it carries every earlier
        # message id. Mark those predecessors covered, but never jump a
        # disjoint exact-id batch.
        if matched_index:
            matched_ids = set(self.pending[matched_index].message_ids)
            predecessors = self.pending[:matched_index]
            if all(set(wake.message_ids) <= matched_ids for wake in predecessors):
                for wake in predecessors:
                    wake.confirmed = True

        confirmed = 0
        message_ids: list[int] = []
        for wake in self.pending:
            if not wake.confirmed:
                break
            confirmed += 1
            message_ids.extend(wake.message_ids)
        if not confirmed:
            return
        credit = adapter.att.get("confirm_delivery_ids")
        ordered_ids = list(dict.fromkeys(message_ids))
        if credit is not None and await credit(ordered_ids):
            for wake in self.pending[:confirmed]:
                if waiter := self._waiters.get(wake.message_ids):
                    self._results[wake.message_ids] = True
                    waiter.set()
            del self.pending[:confirmed]

    async def wait(self, message_ids: list[int]) -> bool:
        key = tuple(message_ids)
        waiter = self._waiters.get(key)
        if waiter is None:
            return False
        await waiter.wait()
        self._waiters.pop(key, None)
        return self._results.pop(key, False)

    def stop(self) -> None:
        self._expected_waits.clear()
        for key, waiter in self._waiters.items():
            self._results[key] = False
            waiter.set()
