"""Sequential process reattachment after a deliberate dogfood restart."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .adapters import Adapter
from .contracts import (
    Event,
    ReattachCandidateResponse,
    ReattachCommand,
    ReattachDecisionEvent,
    ReattachOfferEvent,
)
from .db import Db, RestartPlan

READY_TIMEOUT_SECONDS = 90.0


class ReattachRuntime(Protocol):
    """The narrow runtime edge used by the restart coordinator."""

    db: Db
    live: dict[str, Adapter]

    async def post_message(
        self, conv_id: str, sender: str, sender_type: str, body: str
    ) -> dict: ...

    async def broadcast(self, conv_id: str, event: Event) -> None: ...


ResumeAttachment = Callable[[str], Awaitable[Adapter]]


@dataclass(frozen=True)
class ReattachResult:
    ready: tuple[str, ...]
    failed: tuple[str, ...]


class ReattachCoordinator:
    """Resume and wake one attachment fully before starting the next."""

    def __init__(
        self,
        runtime: ReattachRuntime,
        resume_attachment: ResumeAttachment,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
    ):
        self.runtime = runtime
        self.resume_attachment = resume_attachment
        self.ready_timeout = ready_timeout

    def offer(self, conv_id: str) -> ReattachOfferEvent | None:
        plan = self.runtime.db.get_restart_plan()
        if plan is None or plan["conversation_id"] != conv_id:
            return None
        attachments = []
        for attachment_id in plan["attachment_ids"]:
            attachment = self.runtime.db.get_attachment(attachment_id)
            if attachment is not None and attachment["conv_id"] == conv_id:
                attachments.append(
                    ReattachCandidateResponse(
                        id=attachment["id"],
                        name=attachment["name"],
                        adapter=attachment["adapter"],
                    )
                )
        if not attachments:
            return None
        return ReattachOfferEvent(
            conversation_id=conv_id,
            token=plan["token"],
            attachments=attachments,
            debrief=plan["debrief"],
        )

    async def choose(self, conv_id: str, data: object, accepted_by: str) -> str | None:
        """Consume an exact offer, returning user-facing validation text on refusal."""
        try:
            command = ReattachCommand.model_validate(data)
        except ValueError:
            return "invalid reattachment choice"
        plan = self.runtime.db.take_restart_plan(conv_id, command.token)
        if plan is None:
            return "that reattachment offer is no longer available"

        action = "started" if command.action == "accept" else "cancelled"
        await self.runtime.broadcast(
            conv_id,
            ReattachDecisionEvent(
                conversation_id=conv_id,
                token=command.token,
                action=action,
            ),
        )
        if command.action == "accept":
            await self.run(plan, accepted_by)
        else:
            await self.runtime.post_message(
                conv_id,
                "system",
                "system",
                f"☏ @{accepted_by} declined process reattachment after restart",
            )
        return None

    async def run(self, plan: RestartPlan, accepted_by: str) -> ReattachResult:
        conv_id = plan["conversation_id"]
        debrief = plan["debrief"].strip() or "Continue the work that was interrupted by the restart."
        await self.runtime.post_message(
            conv_id,
            "system",
            "system",
            f"☏ @{accepted_by} accepted sequential reattachment after the dogfood restart\n\n"
            f"Continuation debrief: {debrief}",
        )

        ready: list[str] = []
        failed: list[str] = []
        for attachment_id in plan["attachment_ids"]:
            attachment = self.runtime.db.get_attachment(attachment_id)
            if attachment is None or attachment["conv_id"] != conv_id:
                failed.append(attachment_id)
                continue

            name = attachment["name"]
            try:
                adapter = await self.resume_attachment(attachment_id)
                pending = self.runtime.db.messages_after(
                    conv_id,
                    attachment["last_seen"],
                    exclude_sender=name,
                )
                if pending:
                    self.runtime.db.set_last_seen(attachment_id, pending[-1]["id"])
                    await adapter.deliver(pending)
                is_ready = await asyncio.wait_for(
                    adapter.wait_ready(), timeout=self.ready_timeout
                )
                if not is_ready:
                    raise RuntimeError("the process exited before claiming its session")
            except TimeoutError:
                failed.append(name)
                await self._abandon(attachment_id)
                await self.runtime.post_message(
                    conv_id,
                    "system",
                    "system",
                    f"⚠ @{name} could not reattach safely: readiness timed out after "
                    f"{self.ready_timeout:g}s",
                )
                continue
            except Exception as exc:
                failed.append(name)
                await self._abandon(attachment_id)
                await self.runtime.post_message(
                    conv_id,
                    "system",
                    "system",
                    f"⚠ @{name} could not reattach safely: {exc}",
                )
                continue

            ready.append(name)
            await self.runtime.post_message(
                conv_id,
                "system",
                "system",
                f"☏ @{name} is ready after restart; advancing to the next process",
            )

        summary = f"{len(ready)} ready"
        if failed:
            summary += f", {len(failed)} failed"
        await self.runtime.post_message(
            conv_id,
            "system",
            "system",
            f"☏ sequential reattachment finished — {summary}",
        )
        return ReattachResult(tuple(ready), tuple(failed))

    async def _abandon(self, attachment_id: str) -> None:
        adapter = self.runtime.live.pop(attachment_id, None)
        if adapter is not None:
            try:
                await adapter.stop()
            except Exception:
                self.runtime.db.set_attachment_status(attachment_id, "exited")
