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
MAX_AUTOMATIC_ATTEMPTS = 2


class ReattachRuntime(Protocol):
    """The narrow runtime edge used by the restart coordinator."""

    db: Db
    live: dict[str, Adapter]
    reattaching: set[str]

    async def post_message(
        self, conv_id: str, sender: str, sender_type: str, body: str
    ) -> dict: ...

    async def broadcast(self, conv_id: str, event: Event) -> None: ...


@dataclass(frozen=True)
class ResumedAttachment:
    adapter: Adapter
    startup_delivery_staged: bool


ResumeAttachment = Callable[[str, list[dict]], Awaitable[ResumedAttachment]]


@dataclass(frozen=True)
class ReattachResult:
    ready: tuple[str, ...]
    failed: tuple[str, ...]
    # Resumed, alive, and still settling when we stopped waiting. Not a failure:
    # the process is on the line and will finish claiming its session on its own
    # schedule. Counted separately so a run that was merely slow cannot be read
    # as a run that lost processes.
    slow: tuple[str, ...] = ()
    unconfirmed: tuple[str, ...] = ()


class ContinuationDeliveryPending(RuntimeError):
    """Automatic recovery stayed live but did not confirm every continuation."""


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
            result = await self.run(plan, None, guard)
            if result.unconfirmed:
                names = ", ".join(result.unconfirmed)
                if plan["attempt_count"] < MAX_AUTOMATIC_ATTEMPTS:
                    raise ContinuationDeliveryPending(
                        f"continuation delivery remains unconfirmed for {names}; "
                        "the automatic plan was preserved for one retry"
                    )
                mentions = ", ".join(f"@{name}" for name in result.unconfirmed)
                debrief = (
                    plan["debrief"].strip()
                    or "Continue the work that was interrupted by the restart."
                )
                first_line = debrief.splitlines()[0]
                await self.runtime.post_message(
                    plan["conversation_id"],
                    "system",
                    "system",
                    f"⚠ automatic continuation abandoned after "
                    f"{plan['attempt_count']} attempts for {mentions}. "
                    f"The processes were left running. Debrief: {first_line}",
                )
                self.runtime.reattaching.difference_update(plan["attachment_ids"])
            return result
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
        unconfirmed: list[str] = []
        unconfirmed_ids: set[str] = set()
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
                continuation_confirmed = False
                try:
                    pending = self.runtime.db.messages_after(
                        conv_id,
                        attachment["last_seen"],
                        exclude_sender=name,
                    )
                    resumed = await self.resume_attachment(attachment_id, pending)
                    adapter = resumed.adapter
                    continuation_confirmed = not pending
                    if pending and resumed.startup_delivery_staged:
                        # The immutable argv removes the pty timing race, but
                        # process creation still proves only intent. Advance
                        # the cursor after the claimed structured transcript
                        # records that digest as user input.
                        delivered = await asyncio.wait_for(
                            adapter.wait_startup_delivery_received(),
                            timeout=self.ready_timeout,
                        )
                        if not delivered:
                            raise RuntimeError(
                                "the process exited before accepting its continuation"
                            )
                        if not self.runtime.db.set_last_seen(
                            attachment_id,
                            pending[-1]["id"],
                            adapter.att.get("runtime_owner"),
                        ):
                            raise RuntimeError(
                                "attachment ownership changed before cursor advancement"
                            )
                        continuation_confirmed = True

                    is_ready = await asyncio.wait_for(
                        adapter.wait_ready(), timeout=self.ready_timeout
                    )
                    if not is_ready:
                        raise RuntimeError("the process exited before claiming its session")

                    if pending and not resumed.startup_delivery_staged:
                        runtime_owner = adapter.att.get("runtime_owner")
                        async with self.runtime.db.reserve_attachment_delivery(
                            attachment_id, runtime_owner
                        ) as reserved:
                            if not reserved:
                                raise RuntimeError(
                                    "attachment ownership changed before continuation delivery"
                                )
                            await adapter.deliver(pending)
                            if not self.runtime.db.set_last_seen(
                                attachment_id,
                                pending[-1]["id"],
                                runtime_owner,
                            ):
                                raise RuntimeError(
                                    "attachment ownership changed during continuation delivery"
                                )
                        continuation_confirmed = True
                    self.runtime.reattaching.discard(attachment_id)
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
                    if continuation_confirmed:
                        slow.append(name)
                        detail = "still settling"
                    else:
                        unconfirmed.append(name)
                        unconfirmed_ids.add(attachment_id)
                        detail = "running but its continuation is still unconfirmed"
                    await self.runtime.post_message(
                        conv_id,
                        "system",
                        "system",
                        f"☏ @{name} is back but {detail} after {self.ready_timeout:g}s — "
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
            # An unconfirmed process stays queued: routing another mention to
            # its not-yet-ready pty would repeat the same loss this guard just
            # detected. Automatic plans remain durable and retry on restart.
            self.runtime.reattaching.difference_update(
                attachment_id
                for attachment_id in attachment_ids
                if attachment_id not in unconfirmed_ids
            )

        summary = f"{len(ready)} ready"
        if slow:
            summary += f", {len(slow)} still settling"
        if failed:
            summary += f", {len(failed)} failed"
        if unconfirmed:
            summary += f", {len(unconfirmed)} continuation unconfirmed"
        await self.runtime.post_message(
            conv_id,
            "system",
            "system",
            f"☏ sequential reattachment finished — {summary}",
        )
        return ReattachResult(
            tuple(ready), tuple(failed), tuple(slow), tuple(unconfirmed)
        )

    async def _abandon(self, attachment_id: str) -> None:
        adapter = self.runtime.live.pop(attachment_id, None)
        if adapter is not None:
            try:
                await adapter.stop()
            except Exception:
                await self.runtime.db.set_attachment_status_async(
                    attachment_id, "exited", adapter.att.get("runtime_owner")
                )
