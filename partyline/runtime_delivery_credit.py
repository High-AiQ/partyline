"""Transcript proof and high-water cursor accounting for wake delivery."""

from __future__ import annotations

import asyncio
import logging
import time

from .adapter_capabilities import transcript_claimed
from .adapters import Adapter

logger = logging.getLogger(__name__)
CLAIM_RETRY_DIAGNOSTIC_SECONDS = 5.0
UNCREDITED_DELIVERY_WARNING_SECONDS = 300.0


class DeliveryCreditMixin:
    """Keep unproved transcript pastes from being repeated or skipped."""

    def _live_uncredited(self, att_id: str, runtime_owner: str | None) -> set[int] | None:
        """Return this activation's outstanding ids, dropping stale owners."""
        entry = self.uncredited.get(att_id)
        if entry is None:
            return None
        if entry["owner"] != runtime_owner:
            del self.uncredited[att_id]
            self.unclaimed_noticed.discard(att_id)
            return None
        return entry["ids"]

    def _record_unproved(self, att: dict, adapter: Adapter, pending: list[dict]) -> None:
        """Suppress repeat pastes until their own transcript proof or retry."""
        now = time.monotonic()
        entry = self.uncredited.setdefault(
            att["id"], {
                "owner": adapter.att.get("runtime_owner"), "ids": set(),
                "confirmed": set(), "uncredited_since": now, "warned_ids": set(),
            }
        )
        entry.setdefault("confirmed", set())
        entry.setdefault("uncredited_since", now)
        entry.setdefault("warned_ids", set())
        entry["delivery_proof"] = (adapter.att.get("adapter_metadata") or {}).get(
            "delivery_proof"
        )
        ids = {m["id"] for m in pending}
        entry["ids"].update(ids)
        try:
            asyncio.get_running_loop().create_task(
                self._diagnose_uncredited_delivery(
                    att["id"], adapter.att.get("runtime_owner"), ids,
                    entry["uncredited_since"],
                )
            )
        except RuntimeError:
            pass

    async def _diagnose_uncredited_delivery(
        self, att_id: str, runtime_owner: str | None, message_ids: set[int], since: float
    ) -> None:
        await asyncio.sleep(UNCREDITED_DELIVERY_WARNING_SECONDS)
        entry = self.uncredited.get(att_id)
        attachment = self.db.get_attachment(att_id)
        if (
            attachment is None
            or attachment.get("runtime_owner") != runtime_owner
            or entry is None
            or entry.get("owner") != runtime_owner
        ):
            return
        pending = sorted((message_ids & entry["ids"]) - entry.get("confirmed", set()))
        fresh = [message_id for message_id in pending
                 if message_id not in entry["warned_ids"]]
        if not fresh:
            return
        entry["warned_ids"].update(fresh)
        logger.warning(
            "transcript delivery remains uncredited: attachment=%s adapter=%s ids=%s age=%.0fs",
            att_id, attachment.get("adapter", "unknown"), fresh,
            time.monotonic() - since,
        )

    async def credit_at_turn_end(self, att_id: str, runtime_owner: str | None) -> None:
        """Use a structured turn-end receipt as weaker proof for fallback adapters."""
        attachment = self.db.get_attachment(att_id)
        adapter = self.live.get(att_id)
        entry = self.uncredited.get(att_id)
        if (
            attachment is None or attachment.get("runtime_owner") != runtime_owner
            or adapter is None or adapter.att.get("runtime_owner") != runtime_owner
            or entry is None or entry.get("owner") != runtime_owner
            or entry.get("delivery_proof") not in {"receipt-boundary", "none-with-reason"}
        ):
            return
        ids = sorted(entry["ids"])
        if not ids:
            return
        metadata = adapter.att.get("adapter_metadata") or {}
        warned = getattr(adapter, "_delivery_boundary_warning_logged", False)
        if not warned:
            adapter._delivery_boundary_warning_logged = True
            logger.warning(
                "delivery credited at turn-end boundary without transcript proof: "
                "attachment=%s adapter=%s ids=%s reason=%s",
                att_id, attachment.get("adapter", "unknown"), ids,
                metadata.get("delivery_proof_reason", "transcript user input is unavailable"),
            )
        await self.confirm_delivery_ids(att_id, ids, runtime_owner, _boundary=True)

    def credit_unclaimed(self, att_id: str, runtime_owner: str | None) -> list[int] | None:
        """Release pre-claim pastes for retry; a claim alone credits none."""
        adapter = self.live.get(att_id)
        if adapter is None or not transcript_claimed(adapter):
            return None
        entry = self.uncredited.get(att_id)
        if (
            entry is None
            or entry["owner"] != runtime_owner
            or not entry.get("claim_pending")
        ):
            return None
        entry["claim_pending"] = False
        entry["claim_retry_pending"] = True
        entry["claim_retry_at"] = time.monotonic()
        message_ids = sorted(entry["ids"])
        return message_ids

    def transcript_claimed(self, att_id: str, runtime_owner: str | None) -> None:
        """Retry released pre-claim wakes as soon as readiness opens."""
        message_ids = self.credit_unclaimed(att_id, runtime_owner)
        if message_ids is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._retry_after_claim(att_id, runtime_owner, message_ids))
        loop.create_task(
            self._diagnose_unretried_claim(att_id, runtime_owner, set(message_ids))
        )

    async def _diagnose_unretried_claim(
        self, att_id: str, runtime_owner: str | None, message_ids: set[int]
    ) -> None:
        await asyncio.sleep(CLAIM_RETRY_DIAGNOSTIC_SECONDS)
        attachment = self.db.get_attachment(att_id)
        entry = self.uncredited.get(att_id)
        if (
            attachment is None
            or attachment.get("runtime_owner") != runtime_owner
            or entry is None
            or entry["owner"] != runtime_owner
        ):
            return
        pending = message_ids & entry["ids"]
        if pending:
            logger.warning(
                "transcript claim retry still uncredited: attachment=%s pending=%d age=%.1fs",
                att_id,
                len(pending),
                time.monotonic() - entry.get("claim_retry_at", time.monotonic()),
            )

    async def _retry_after_claim(
        self, att_id: str, runtime_owner: str | None, message_ids: list[int]
    ) -> None:
        attachment = self.db.get_attachment(att_id)
        adapter = self.live.get(att_id)
        if (
            attachment is None
            or attachment.get("runtime_owner") != runtime_owner
            or adapter is None
            or adapter.att.get("runtime_owner") != runtime_owner
        ):
            return
        repool = adapter.att.get("repool_message_ids")
        if repool is not None and await repool(message_ids):
            # Presence persists this exact batch and flushes it only after the
            # active turn ends. Directly addressed wakes otherwise bypass its
            # normal busy hold. Keep runtime suppression until that handoff.
            entry = self.uncredited.get(att_id)
            if entry is not None and entry["owner"] == runtime_owner:
                entry["ids"].difference_update(message_ids)
                entry.setdefault("confirmed", set()).difference_update(message_ids)
                entry.pop("claim_retry_pending", None)
                if not entry["ids"]:
                    self.uncredited.pop(att_id, None)
                    self.unclaimed_noticed.discard(att_id)
        else:
            entry = self.uncredited.get(att_id)
            if entry is not None and entry["owner"] == runtime_owner:
                entry["claim_pending"] = True
                entry.pop("claim_retry_pending", None)

    async def confirm_delivery_ids(
        self, att_id: str, message_ids: list[int], runtime_owner: str | None,
        *, _boundary: bool = False,
    ) -> bool:
        """Credit proven ids without letting a later proof jump an earlier gap."""
        if not message_ids:
            return False
        adapter = self.live.get(att_id)
        metadata = (adapter.att.get("adapter_metadata") or {}) if adapter else {}
        if metadata.get("delivery_proof") == "none-with-reason" and not _boundary:
            return False
        async with self.db.reserve_attachment_delivery(att_id, runtime_owner) as reserved:
            if not reserved:
                return False
            entry = self.uncredited.get(att_id)
            if entry is not None and entry["owner"] != runtime_owner:
                del self.uncredited[att_id]
                entry = None
            if entry is None:
                entry = {"owner": runtime_owner, "ids": set(), "confirmed": set()}
                self.uncredited[att_id] = entry
            entry.setdefault("confirmed", set())
            ids = set(message_ids)
            entry["ids"].update(ids)
            entry["confirmed"].update(ids)
            attachment = self.db.get_attachment(att_id)
            if attachment is None or attachment.get("runtime_owner") != runtime_owner:
                return False
            unresolved = entry["ids"] - entry["confirmed"]
            frontier = min(unresolved) - 1 if unresolved else max(entry["ids"])
            eligible = entry["confirmed"] & {mid for mid in entry["ids"] if mid <= frontier}
            if eligible and not self.db.set_last_seen(att_id, max(eligible), runtime_owner):
                return False
            attachment = self.db.get_attachment(att_id)
            high_water = attachment["last_seen"] if attachment is not None else 0
            credited = {mid for mid in entry["ids"] if mid <= high_water}
            entry["ids"].difference_update(credited)
            entry["confirmed"].difference_update(credited)
            self.db.clear_queued_delivery_ids(att_id, list(credited))
            if not entry["ids"]:
                self.uncredited.pop(att_id, None)
                self.unclaimed_noticed.discard(att_id)
            return max(message_ids) <= high_water

    async def _hold_credit(self, conv_id: str, att: dict, adapter: Adapter, pending: list[dict]):
        """Remember pre-claim pastes and say so once."""
        entry = self.uncredited.setdefault(
            att["id"], {
                "owner": adapter.att.get("runtime_owner"), "ids": set(), "confirmed": set()
            }
        )
        entry["claim_pending"] = True
        entry.setdefault("uncredited_since", time.monotonic())
        entry.setdefault("warned_ids", set())
        ids = {m["id"] for m in pending}
        entry["ids"].update(ids)
        try:
            asyncio.get_running_loop().create_task(
                self._diagnose_uncredited_delivery(
                    att["id"], adapter.att.get("runtime_owner"), ids,
                    entry["uncredited_since"],
                )
            )
        except RuntimeError:
            pass
        if att["id"] in self.unclaimed_noticed:
            return
        self.unclaimed_noticed.add(att["id"])
        plural = "wake" if len(entry["ids"]) == 1 else "wakes"
        await self.post_message(
            conv_id, "system", "system",
            f"⚠ {len(entry['ids'])} {plural} pending for @{att['name']} but it has not claimed "
            "its transcript yet — delivery credit held until it does",
        )

    async def _credit_claimed(self, att: dict, adapter: Adapter):
        """Release only pre-claim ids, then let durable delivery retry them."""
        self.transcript_claimed(att["id"], adapter.att.get("runtime_owner"))
