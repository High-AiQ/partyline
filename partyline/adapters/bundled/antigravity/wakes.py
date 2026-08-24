"""Settlement of pasted wakes against evidence the CLI provides.

A pasted wake is an instruction, and partyline must not credit it as
delivered until the harness shows it acted — or retry when the harness
shows it did not. Two channels give evidence, of unequal strength:

- The pinned log's ``HandleUserInput`` line proves bytes entered the input
  loop. It is our own paste echoed back, so for a wake pasted *mid-turn*
  it proves nothing about ingestion: antigravity accepts mid-turn
  submissions and silently drops them (2026-08-24: two @gemini-flash
  mentions vanished this way). An echo may only settle a wake that was
  pasted while the CLI was idle.
- A transcript ``USER_INPUT`` record containing the digest proves a turn
  began from it. This is the only channel that may settle a wake pasted
  mid-turn.

A turn end is the last court: a wake still outstanding then never began a
turn. After a short grace — a queued submission may land its record just
after the boundary — it repools for redelivery while the CLI is idle.
Resending into a busy TUI is the bit bucket the wake was just lost in, so
no path here ever writes to a mid-turn process.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from . import logparse

# Between a turn ending and a queued submission landing its transcript
# record there is a race; repooling inside it would double-deliver.
REPOOL_GRACE = 10.0

MAX_RESENDS = 2


def _timestamp(created_at) -> float | None:
    """When the record was written, or None if it carries no usable stamp."""
    if not created_at:
        return None
    try:
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class WakeSettlement:
    """Mixin for PartylineAdapter: how pasted wakes are proven or retried."""

    def _contains(self, content: str, probe: str) -> bool:
        """Whitespace-normalized containment: the TUI may reflow a long paste,
        so a digest matches the submitted input up to whitespace runs."""
        return bool(probe) and " ".join(probe.split()) in " ".join(content.split())

    async def _note_user_input(self, content: str, created_at, *, transcript: bool = True):
        """Settle outstanding wakes against one submitted-input record.

        A record may only judge wakes pasted before it was written: a
        mention delivered mid-turn pastes a wake that an already-written
        record cannot contain, and judging it anyway would call a healthy
        paste skipped. Contained wakes are verified — unless the record is
        a log echo of a mid-turn paste, which is not evidence of anything.
        An uncontained wake pasted while idle is re-sent up to
        ``MAX_RESENDS`` times; a wake touched by a busy CLI holds for the
        turn-end settlement instead of being re-fed to the bit bucket.
        """
        created = _timestamp(created_at)
        kept: list[tuple] = []
        for digest, pasted_at, message_ids, mid_turn in self._outstanding:
            if created is not None and pasted_at >= created:
                kept.append((digest, pasted_at, message_ids, mid_turn))
                continue
            if self._contains(content, digest):
                if mid_turn and not transcript:
                    kept.append((digest, pasted_at, message_ids, mid_turn))
                    continue
                self._notices = 0
                self._resend_counts.pop(digest, None)
                continue
            if mid_turn or self._turn_open:
                kept.append((digest, pasted_at, message_ids, mid_turn))
                continue
            count = self._resend_counts.get(digest, 0) + 1
            self._resend_counts[digest] = count
            if count <= MAX_RESENDS:
                kept.append((digest, pasted_at, message_ids, mid_turn))
                await self.send_keys(digest)
            else:
                self._resend_counts.pop(digest, None)
                await self._repool(list(message_ids))
                if self._notices < self.MAX_NOTICES:
                    self._notices += 1
                    await self.post(
                        "system", "system",
                        f"{self.att['name']}: the CLI submitted other input after "
                        "this wake was pasted — wake queued for next turn-end",
                    )
        self._outstanding = kept

    async def _note_log_line(self, line: str) -> None:
        """Settle outstanding wakes against a logged submission.

        The pinned log's HandleUserInput line is written at submit time, so
        it judges minutes before the transcript can — but only for wakes
        pasted while idle. A line without a parseable timestamp cannot
        judge — degraded evidence is not a verdict.
        """
        if parsed := logparse.submission(line):
            await self._note_user_input(*parsed, transcript=False)

    async def _settle_turn_end(self) -> None:
        """Repool wakes a finished turn proves were never ingested."""
        if not self._outstanding or not self.alive():
            return
        doomed = {wake[2] for wake in self._outstanding}
        await asyncio.sleep(REPOOL_GRACE)
        survivors = [wake for wake in self._outstanding if wake[2] in doomed]
        self._outstanding = [wake for wake in self._outstanding if wake[2] not in doomed]
        if not survivors:
            return
        self._resend_counts.clear()
        ids = [message_id for wake in survivors for message_id in wake[2]]
        await self._repool(ids)
        if self._notices < self.MAX_NOTICES:
            self._notices += 1
            await self.post(
                "system", "system",
                f"{self.att['name']}: a wake accepted mid-turn never began a "
                "turn — re-delivering while the CLI is idle",
            )

    async def _repool(self, message_ids: list[int]) -> None:
        repool = self.att.get("repool_message_ids")
        if repool is not None and message_ids:
            await repool(message_ids)
