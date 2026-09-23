"""Per-paste OpenCode receipts and idle redelivery."""

from __future__ import annotations

import asyncio
import json

REPOOL_GRACE = 1.0


def _normal(text: str) -> str:
    return " ".join(text.split())


class WakeSettlement:
    """Settle each paste only against its matching OpenCode user part."""

    def _wakes_init(self) -> None:
        self._wake_receipts: list[dict] = []
        self._repool_task: asyncio.Task | None = None
        self._confirmed_delivery_ids: set[int] = set()
        self._delivery_confirmed = asyncio.Event()
        self._seen_user_parts: set[str] = set()

    async def stop(self):
        if self._repool_task is not None:
            self._repool_task.cancel()
        await super().stop()  # type: ignore[misc]

    async def deliver(self, messages: list[dict]):
        """Wait for structured readiness, then keep this paste uncredited."""
        if self._ready_result is not True and not await self.wait_ready():  # type: ignore[attr-defined]
            return False
        digest = self.format_digest(messages)  # type: ignore[attr-defined]
        ids = [m["id"] for m in messages if isinstance(m.get("id"), int)]
        marker = self._new_paste_marker()  # type: ignore[attr-defined]
        self._pending_paste_marker = marker  # type: ignore[attr-defined]
        wake = None
        if digest.strip() and ids:
            wake = {
                "digest": _normal(digest), "marker": marker, "ids": ids, "proven": False,
            }
            self._wake_receipts.append(wake)
        try:
            await super().deliver(messages)  # type: ignore[misc]
        except BaseException:
            if wake is not None:
                self._wake_receipts = [item for item in self._wake_receipts if item is not wake]
            self._pending_paste_marker = None  # type: ignore[attr-defined]
            raise
        return False

    async def _observe_user_part(self, raw: str, part_id: str | None = None) -> None:
        if part_id is not None:
            if part_id in self._seen_user_parts:
                return
            self._seen_user_parts.add(part_id)
        try:
            text = json.loads(raw).get("text", "")
        except (TypeError, json.JSONDecodeError, AttributeError):
            return
        if not isinstance(text, str):
            return
        observed = _normal(text)
        # Each part is one input event and can prove at most one paste.
        for wake in self._wake_receipts:
            if not wake["proven"] and wake["marker"] in observed:
                wake["proven"] = True
                break
        confirm = self.att.get("confirm_delivery_ids")  # type: ignore[attr-defined]
        while confirm is not None:
            kept = []
            progressed = False
            for wake in self._wake_receipts:
                if not wake["proven"] or not await confirm(wake["ids"]):
                    kept.append(wake)
                    continue
                self._confirmed_delivery_ids.update(wake["ids"])
                self._delivery_confirmed.set()
                progressed = True
            self._wake_receipts = kept
            if not progressed:
                break

    def prepare_delivery_receipt(self, message_ids: list[int]) -> None:
        self._delivery_confirmed.clear()

    async def wait_delivery_received(self, message_ids: list[int]) -> bool:
        """Wait for exact transcript evidence and host cursor credit."""
        wanted = set(message_ids)
        while not wanted <= self._confirmed_delivery_ids:
            if not self.alive():  # type: ignore[attr-defined]
                return False
            self._delivery_confirmed.clear()
            try:
                await asyncio.wait_for(self._delivery_confirmed.wait(), timeout=1.0)
            except TimeoutError:
                continue
        return True

    def _schedule_unproved_repool(self) -> None:
        if self._wake_receipts and (self._repool_task is None or self._repool_task.done()):
            self._repool_task = asyncio.create_task(self._repool_unproved())

    async def _repool_unproved(self) -> None:
        await asyncio.sleep(REPOOL_GRACE)
        doomed = [wake for wake in self._wake_receipts if not wake["proven"]]
        self._wake_receipts = [wake for wake in self._wake_receipts if wake["proven"]]
        ids = [message_id for wake in doomed for message_id in wake["ids"]]
        repool = self.att.get("repool_message_ids")  # type: ignore[attr-defined]
        if ids and repool is not None:
            await repool(ids)
