"""Sequential process reattachment after a deliberate dogfood restart."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .adapters import Adapter
from .contracts import (
    Event,
    ReattachCandidateResponse,
    ReattachCommand,
    ReattachDecisionEvent,
    ReattachOfferEvent,
    RestartPlanRequest,
    RestartPlanResponse,
)
from .db import Db, RestartPlan
from .restart_lease import run_automatic_restart_plan

READY_TIMEOUT_SECONDS = 90.0


class ReattachRuntime(Protocol):
    """The narrow runtime edge used by the restart coordinator."""

    db: Db
    live: dict[str, Adapter]
    reattaching: set[str]

    async def post_message(
        self, conv_id: str, sender: str, sender_type: str, body: str
    ) -> dict: ...

    async def broadcast(self, conv_id: str, event: Event) -> None: ...


ResumeAttachment = Callable[[str], Awaitable[Adapter]]


@dataclass(frozen=True)
class ReattachResult:
    ready: tuple[str, ...]
    failed: tuple[str, ...]
    # Resumed, alive, and still settling when we stopped waiting. Not a failure:
    # the process is on the line and will finish claiming its session on its own
    # schedule. Counted separately so a run that was merely slow cannot be read
    # as a run that lost processes.
    slow: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestartPlanError(Exception):
    status_code: int
    detail: str


def adapter_can_resume(metadata: Mapping[str, object]) -> bool:
    capabilities = metadata.get("capabilities") or {}
    return (
        bool(capabilities.get("resume", False))
        if isinstance(capabilities, dict)
        else "resume" in capabilities
    )


def restart_plan_response(db: Db, plan: RestartPlan) -> RestartPlanResponse:
    attachments = []
    for attachment_id in plan["attachment_ids"]:
        attachment = db.get_attachment(attachment_id)
        if attachment is not None and attachment["conv_id"] == plan["conversation_id"]:
            attachments.append(
                ReattachCandidateResponse(
                    id=attachment["id"],
                    name=attachment["name"],
                    adapter=attachment["adapter"],
                )
            )
    return RestartPlanResponse(
        conversation_id=plan["conversation_id"],
        token=plan["token"],
        attachments=attachments,
        debrief=plan["debrief"],
    )


def create_restart_plan(
    runtime: ReattachRuntime,
    adapter_metadata: Mapping[str, Mapping[str, object]],
    body: RestartPlanRequest,
) -> RestartPlanResponse:
    conversation = runtime.db.get_conversation(body.conversation_id)
    if conversation is None or conversation["archived_at"]:
        raise RestartPlanError(404, "the requesting line is not available")
    attachment_ids = [
        attachment["id"]
        for attachment in runtime.db.list_attachments(body.conversation_id)
        if attachment["id"] in runtime.live
        and attachment["status"] in ("starting", "running")
        and adapter_can_resume(adapter_metadata.get(attachment["adapter"], {}))
    ]
    if not attachment_ids:
        raise RestartPlanError(409, "this line has no resumable live processes")
    plan = runtime.db.save_restart_plan(
        body.conversation_id,
        attachment_ids,
        body.debrief.strip(),
        body.mode,
    )
    return restart_plan_response(runtime.db, plan)


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
        if (
            plan is None
            or plan["mode"] != "offer"
            or plan["conversation_id"] != conv_id
        ):
            return None
        response = restart_plan_response(self.runtime.db, plan)
        if not response.attachments:
            return None
        return ReattachOfferEvent(
            conversation_id=conv_id,
            token=plan["token"],
            attachments=response.attachments,
            debrief=plan["debrief"],
        )

    async def choose(self, conv_id: str, data: object, accepted_by: str) -> str | None:
        """Consume an exact offer, returning user-facing validation text on refusal."""
        try:
            command = ReattachCommand.model_validate(data)
        except ValueError:
            return "invalid reattachment choice"
        plan = self.runtime.db.take_restart_plan(conv_id, command.token, "offer")
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

    async def run_automatic(self) -> ReattachResult | None:
        """Run a trusted cockpit plan under recoverable, exclusive ownership."""
        async def operation(plan: RestartPlan, guard: Callable[[], None]) -> ReattachResult:
            return await self.run(plan, None, guard)
        return await run_automatic_restart_plan(self.runtime.db, operation)

    async def run(
        self,
        plan: RestartPlan, accepted_by: str | None,
        ensure_owned: Callable[[], None] | None = None,
    ) -> ReattachResult:
        conv_id = plan["conversation_id"]
        debrief = plan["debrief"].strip() or "Continue the work that was interrupted by the restart."
        start = (
            f"@{accepted_by} accepted sequential reattachment"
            if accepted_by is not None
            else "the trusted cockpit plan started automatic sequential reattachment"
        )
        attachment_ids = plan["attachment_ids"]
        if ensure_owned is not None:
            ensure_owned()
        self.runtime.reattaching.update(attachment_ids)
        try:
            await self.runtime.post_message(
                conv_id,
                "system",
                "system",
                f"☏ {start} after the dogfood restart\n\n"
                f"Continuation debrief: {debrief}",
            )
        except BaseException:
            self.runtime.reattaching.difference_update(attachment_ids)
            raise
        ready: list[str] = []
        failed: list[str] = []
        slow: list[str] = []
        try:
            for attachment_id in attachment_ids:
                if ensure_owned is not None:
                    ensure_owned()
                attachment = self.runtime.db.get_attachment(attachment_id)
                if attachment is None or attachment["conv_id"] != conv_id:
                    failed.append(attachment_id)
                    self.runtime.reattaching.discard(attachment_id)
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
                    self.runtime.reattaching.discard(attachment_id)
                    is_ready = await asyncio.wait_for(
                        adapter.wait_ready(), timeout=self.ready_timeout
                    )
                    if not is_ready:
                        raise RuntimeError("the process exited before claiming its session")
                except TimeoutError:
                    # Slow is not failed, and killing it is the only real harm.
                    #
                    # Readiness means "the adapter has opened its claimed
                    # transcript". For a resumed codex that file is written lazily,
                    # on the first turn's flush — its own source says the rollout
                    # "may not appear for many minutes". Stopping the process at 90s
                    # took down three healthy agents that were on their way back.
                    #
                    # The wait still earns its place: when readiness does arrive the
                    # next process starts immediately behind it. What it must not do
                    # is treat its own impatience as evidence of a broken process.
                    slow.append(name)
                    await self.runtime.post_message(
                        conv_id,
                        "system",
                        "system",
                        f"☏ @{name} is back but still settling after {self.ready_timeout:g}s — "
                        f"left running, advancing to the next process",
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
        finally:
            self.runtime.reattaching.difference_update(attachment_ids)

        summary = f"{len(ready)} ready"
        if slow:
            summary += f", {len(slow)} still settling"
        if failed:
            summary += f", {len(failed)} failed"
        await self.runtime.post_message(
            conv_id,
            "system",
            "system",
            f"☏ sequential reattachment finished — {summary}",
        )
        return ReattachResult(tuple(ready), tuple(failed), tuple(slow))

    async def _abandon(self, attachment_id: str) -> None:
        adapter = self.runtime.live.pop(attachment_id, None)
        if adapter is not None:
            try:
                await adapter.stop()
            except Exception:
                self.runtime.db.set_attachment_status(attachment_id, "exited")
