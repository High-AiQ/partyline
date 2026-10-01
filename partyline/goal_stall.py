"""Delay idle notices until line activity has gone quiet."""

from __future__ import annotations

import asyncio

from .hierarchy import ancestors, parent_id_of, subtree_conversation_ids
from .mention_relay import LIVE, lead_attachment, live_manager, post_private

QUIET_NOTICE_SECONDS = 10
CAP_NOTICE_SECONDS = 1200


def quiet_deadline(runtime, att_id: str, ended_at: float) -> float:
    adapter = getattr(runtime, "live", {}).get(att_id)
    quiet_at = getattr(adapter, "last_output_at", 0.0) + QUIET_NOTICE_SECONDS
    return min(quiet_at, ended_at + CAP_NOTICE_SECONDS)


async def wait_until_quiet(runtime, presence, att_id, ended_at, clock, sleep) -> bool:
    while presence is None or not presence.is_working(att_id):
        delay = quiet_deadline(runtime, att_id, ended_at) - clock()
        if delay <= 0:
            return True
        await sleep(delay)
    return False


class GoalStallGuard:
    """Wake one captain after a quiet goal line."""

    def __init__(self, runtime, presence):
        self.runtime, self.presence = runtime, presence
        self.notified, self.woken, self.suppressed, self.pending = set(), {}, {}, {}

    def activity(self, conv_id: str, actor_id: str | None = None) -> None:
        if getattr(self.runtime, "db", None) is None:
            return
        if actor_id and actor_id in self.woken:
            self.suppressed.setdefault(actor_id, set()).update(self.woken.pop(actor_id))
            return
        line_ids = [conv_id, *ancestors(self.runtime.db, conv_id)]
        if actor_id and self.suppressed.get(actor_id, set()).intersection(line_ids):
            return
        for line in line_ids:
            self.notified.discard(line)
            if task := self.pending.pop(line, None):
                task.cancel()
        for recipient, lines in list(self.suppressed.items()):
            lines.difference_update(line_ids)
            if not lines:
                self.suppressed.pop(recipient)

    def return_notice(self, recipient: dict, finisher: dict, *, deferred: bool = False) -> None:
        if getattr(self.runtime, "db", None) is None:
            return
        recipient_id = recipient.get("id")
        lines = {finisher.get("conv_id")}
        if recipient.get("is_lead"):
            lines.add(recipient.get("conv_id"))
        for line in lines - {None}:
            conv = self.runtime.db.get_conversation(line)
            if conv:
                covered = [line, *ancestors(self.runtime.db, line)]
                self.notified.update(covered)
                if recipient_id:
                    self.woken.setdefault(recipient_id, set()).update(covered)

    def _blocked(self, conv_id: str) -> bool:
        lines = subtree_conversation_ids(self.runtime.db, conv_id)
        return any(
            row["status"] == "starting" or row["status"] in LIVE and (
                row["id"] in self.runtime.returns.pending
                or row["id"] in self.runtime.returns.requesters
                or row["id"] in self.runtime.returns.askers
                or self.presence.is_working(row["id"])
                or self.presence.queue.held_count(row["id"])
            )
            for line in lines
            for row in self.runtime.db.list_attachments(line)
        )

    def _covered(self, conv_id: str) -> bool:
        return any(line in self.notified for line in [conv_id, *ancestors(self.runtime.db, conv_id)])

    def _target(self, conv_id: str) -> dict | None:
        target = live_manager(self.runtime, conv_id)
        ended = self.runtime.returns.ended_at
        finisher = max(
            (a for a in ended if (r := self.runtime.db.get_attachment(a))
             and r["conv_id"] == conv_id),
            key=ended.get,
            default=None,
        )
        if target and target["id"] == finisher:
            parent = parent_id_of(self.runtime.db.get_conversation(conv_id))
            target = lead_attachment(self.runtime.db, parent) if parent else target
        if target:
            return target if target["status"] in LIVE else None
        root = ancestors(self.runtime.db, conv_id)
        return live_manager(self.runtime, root[-1]) if root else None

    async def check(self, conv_id: str, actor_id: str | None = None) -> None:
        if getattr(self.runtime, "db", None) is None:
            return
        conv = self.runtime.db.get_conversation(conv_id)
        if conv is None or not str(conv.get("goal") or "").strip():
            return
        actor = self.runtime.db.get_attachment(actor_id) if actor_id else None
        if actor and actor["conv_id"] == conv_id and actor.get("is_lead"):
            return
        if (
            self._covered(conv_id) or conv.get("archived_at") or conv_id in self.pending
            or self._blocked(conv_id)
        ):
            return
        self.pending[conv_id] = asyncio.create_task(
            self._wait_and_wake(conv_id, self.runtime.returns.clock())
        )

    async def check_tree(self, conv_id: str) -> None:
        if getattr(self.runtime, "db", None) is None:
            return
        for line in [conv_id, *ancestors(self.runtime.db, conv_id)]:
            await self.check(line)

    async def _wait_and_wake(self, conv_id: str, anchor: float) -> None:
        try:
            returns = self.runtime.returns
            while not self._blocked(conv_id):
                conv = self.runtime.db.get_conversation(conv_id)
                if conv is None or not str(conv.get("goal") or "").strip() or conv.get("archived_at"):
                    return
                now = returns.clock()
                deadlines = [
                    quiet_deadline(self.runtime, row["id"], returns.ended_at.get(row["id"], anchor))
                    for line in subtree_conversation_ids(self.runtime.db, conv_id)
                    for row in self.runtime.db.list_attachments(line)
                    if row["status"] in LIVE
                ]
                delay = max(deadlines, default=now) - now
                if delay > 0:
                    await returns.sleep(delay)
                    continue
                target = self._target(conv_id)
                if target and target["status"] in LIVE:
                    if self._covered(conv_id):
                        return
                    self.notified.update([conv_id, *ancestors(self.runtime.db, conv_id)])
                    name = self.runtime.db.get_conversation(conv_id)["name"]
                    self.woken.setdefault(target["id"], set()).update(
                        [conv_id, *ancestors(self.runtime.db, conv_id)]
                    )
                    await post_private(
                        self.runtime,
                        target["conv_id"],
                        "system",
                        "system",
                        f"☏ goal still open on line «{name}»: {str(conv['goal']).strip()}",
                        audience=target["id"],
                    )
                return
        except asyncio.CancelledError:
            return
        finally:
            if self.pending.get(conv_id) is asyncio.current_task():
                self.pending.pop(conv_id, None)
