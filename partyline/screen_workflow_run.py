"""Execute a pinned plan with one action in flight and event-driven checks."""

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from fastapi import HTTPException

from . import screen_workflow_audit as audit
from .contracts import MessageEvent, MessageResponse
from .file_events import Changes
from .machine_scope import deny_unless
from .screen_workflow_confirm import ConfirmationStops
from .screen_workflow_evidence import (
    StopWorkflow,
    authorized_window,
    capability_error,
    identity,
    matching,
    require_capabilities,
    verdict,
)

logger = logging.getLogger(__name__)
RUN_SECONDS = 45 * 60


class Run(ConfirmationStops):
    def __init__(self, service, run_id, principal, conv_id, grant, device, activation, plan, revision):
        self.service = service
        self.db = service.hub.runtime.db
        self.id = run_id
        self.principal = principal
        self.conv_id = conv_id
        self.grant_id = grant["id"]
        self.socket = device["socket"]
        self.activation = activation
        self.plan = plan
        self.revision = revision
        self.verified = 0
        self.step_id = None
        self.source = None
        self.document = None
        self.intent = False
        self.window_hash = None
        self.resuming = False
        self.observation_key = object()
        self.reason = None
        self.confirmation = None
        self.changes = Changes()
        self.task = None
        self.executing = False

    def starting_attachment(self):
        if self.principal.kind != "machine":
            return None
        att = self.db.get_attachment(self.principal.attachment_id)
        if (
            att
            and att["conv_id"] == self.conv_id
            and att["status"] in ("starting", "running")
            and (att["runtime_owner"], att["api_token"]) == self.activation[1:]
        ):
            return att
        return None

    def authorize(self):
        if self.reason:
            raise StopWorkflow(self.reason, "stopped")
        if not audit.approval(self.db, self.revision):
            raise StopWorkflow("workflow approval revoked", "stopped")
        if self.principal.kind == "machine":
            if not self.starting_attachment():
                raise StopWorkflow("starting attachment ended", "stopped")
        else:
            from .auth_store import user_by_id

            if not user_by_id(self.db, self.principal.user_id):
                raise StopWorkflow("starting account ended", "stopped")
        try:
            if self.service.directory(self.conv_id) != self.activation[0]:
                raise StopWorkflow("line working directory changed", "stopped")
            deny_unless(self.db, self.principal, self.conv_id, "read")
            deny_unless(self.db, self.principal, self.conv_id, "write")
            grant, device = authorized_window(self.service.hub, self.principal, self.grant_id, self.conv_id)
        except HTTPException as exc:
            raise StopWorkflow("window or line authorization ended", "stopped") from exc
        if device["socket"] is not self.socket:
            raise StopWorkflow("screen helper disconnected", "stopped")
        return grant, device

    def require_current(self):
        if not self.revision.current():
            raise StopWorkflow("approved workflow bundle changed", "stopped")

    async def watch_authority(self):
        tables = (
            "attachments",
            "users",
            "conversations",
            "screen_line_window_grants",
            "screen_devices",
            "screen_workflow_approvals",
            "screen_helper_updates",
            "screen_device_window_lines",
            "screen_device_window_access",
        )
        with self.db.events.subscribe(*tables) as changes:
            while True:
                try:
                    self.authorize()
                except StopWorkflow as exc:
                    self.stop(str(exc))
                    return
                await changes.wait()

    def stop(self, reason, actor_id=None):
        if self.reason is not None or self.task.done():
            return
        self.reason = reason
        audit.event(self, "stop_requested", actor_id=actor_id, outcome=reason)
        audit.change(self, "stopping", reason)
        if self.executing:
            self.task.cancel()

    async def post(self, message, *, wake_starter=False):
        runtime = self.service.hub.runtime
        row = self.service.row(self.conv_id, self.id)
        if row is None:
            return
        step = f" · {self.step_id}" if self.step_id else ""
        body = (
            f"Screen workflow {row['workflow']} · run {self.id} · revision {row['revision']} · "
            f"{self.verified}/{len(self.plan)} verified{step} · {message}"
        )
        starter = self.starting_attachment() if wake_starter else None
        if starter:
            body = f"@{starter['name']} {body}"
        event = runtime.db.add_message(self.conv_id, "system", "system", body)
        notice = MessageEvent(message=MessageResponse.model_validate(event))
        # A slow browser must not prevent the server from waking the starter.
        with suppress(TimeoutError):
            async with asyncio.timeout(2):
                await runtime.broadcast(self.conv_id, notice)
        if starter and self.starting_attachment():
            with suppress(TimeoutError):
                async with asyncio.timeout(2):
                    await runtime.route_mentions(
                        self.conv_id, {**event, "audience_attachment_id": starter["id"]}, force=True
                    )

    async def execute(self):
        self.executing = True
        authority = asyncio.create_task(self.watch_authority())
        state, outcome = "completed", "all steps verified"
        deadline = self.service.clock() + RUN_SECONDS
        try:
            async with self.service.timeout_at(deadline):
                await self.execute_plan()
        except StopWorkflow as exc:
            state, outcome = exc.state, str(exc)
        except asyncio.CancelledError:
            state, outcome = "stopped", self.reason or "server stopped"
        except (TimeoutError, OSError, RuntimeError, HTTPException):
            if self.service.clock() >= deadline:
                state, outcome = "stopped", "overall run deadline elapsed"
            else:
                state, outcome = "failed", "screen operation unavailable"
        except Exception:
            # Raw helper exceptions can include screen content. Keep only the exception class.
            logger.error("Unexpected workflow failure in run %s", self.id)
            state, outcome = "failed", "workflow execution error"
        finally:
            self.executing = False
            self.confirmation = None
            authority.cancel()
            if self.verified >= len(self.plan):
                self.step_id = None
            else:
                self.step_id = self.plan[self.verified][0]
            if self.intent:
                outcome += ", input outcome uncertain"
            audit.event(self, "finished", outcome=outcome)
            audit.change(self, state, outcome)
            self.service.release(self)
        await self.service.push_changed(self)
        await self.post(outcome, wake_starter=True)

    async def execute_plan(self):
        self.authorize()
        await self.post("resumed" if self.resuming else "started")
        for step_id, step in self.plan[self.verified:]:
            self.step_id = step_id
            audit.change(self, "running")
            await self.service.push_changed(self)
            await self.perform(step)
            audit.journal(self, "verified")
            self.resuming = False
            if self.verified < len(self.plan) and self.verified % 8 == 0:
                await self.post("in progress")

    async def observe(self, step):
        tree = await self.service.screen.observe(self)
        if tree.changed or tree.partial:
            return None
        _, device = self.authorize()
        if self.source is None:
            self.source = tree.source
        require_capabilities(self.step_id, step, tree.source, device)
        document = identity(tree)
        if document is None:
            raise StopWorkflow("document or window identity is unknown")
        if self.document is not None and (self.document != document or self.source != tree.source):
            raise StopWorkflow("window source or document changed")
        if self.document is None:
            window_hash = audit.fingerprint(self.db, [self.grant_id, tree.source, document])
            if self.window_hash is not None and window_hash != self.window_hash:
                raise StopWorkflow("resumed window source or document changed", "stopped")
            if self.window_hash is None:
                sql = "UPDATE screen_workflow_runs SET window_hash=? WHERE id=?"
                self.db._exec(sql, (window_hash, self.id))
                self.window_hash = window_hash
            for step_id, remaining in self.plan[self.verified:]:
                require_capabilities(step_id, remaining, tree.source, device)
        self.document, self.source = document, tree.source
        return tree

    def target(self, tree, step):
        nodes = matching(tree, step.target)
        if nodes is None:
            raise StopWorkflow("semantic target is ambiguous or match count changed")
        if not nodes:
            if step.allow_point:
                raise StopWorkflow("point input requires the person", "paused")
            raise StopWorkflow("semantic target is missing")
        node = nodes[0]
        if (
            step.action not in node.actions or "disabled" in node.flags
            or node.cached.get("actionable") is False
        ):
            if step.allow_point:
                raise StopWorkflow("point input requires the person", "paused")
            raise capability_error(self.step_id, f"{tree.source}.{step.action}", tree.source)
        if any(verdict(tree, check, step.target) is not True for check in step.preconditions):
            raise StopWorkflow("precondition failed or is unknown")
        return node

    async def perform(self, step):
        self.require_current()
        tree = await self.observe(step)
        if tree is None:
            raise StopWorkflow("screen evidence changed during capture")
        node = self.target(tree, step)
        if self.resuming and self.intent and (
            not step.preconditions or verdict(tree, step.postcondition, step.target) is not False
        ):
            raise StopWorkflow("safe retry could not be verified for previous input", "stopped")
        if step.confirm:
            tree, node = await self.confirm(step, tree, node)
        fresh = (
            step.postcondition.check != "notice_text"
            or verdict(tree, step.postcondition, step.target) is False
        )
        cursor = self.changes.version
        outcome = await self.service.screen.act(self, step, tree, node)
        audit.event(self, "helper_receipt", outcome=outcome)
        await self.verify(step, cursor, fresh, tree.live_events)

    async def verify(self, step, cursor, fresh, live):
        deadline = self.service.clock() + step.postcondition.timeout_ms / 1000
        try:
            async with self.service.timeout_at(deadline):
                while True:
                    self.authorize()
                    read_cursor = self.changes.version
                    observed = await self.observe(step)
                    evidence = verdict(observed, step.postcondition, step.target) if observed else None
                    if observed:
                        live = observed.live_events
                        cursor = read_cursor
                    if evidence is True and fresh:
                        return
                    if evidence is False:
                        fresh = True
                    if not live:
                        raise StopWorkflow("postcondition unknown without a live event feed")
                    await self.changes.wait_after(cursor)
                    cursor = self.changes.version
        except TimeoutError as exc:
            raise StopWorkflow("postcondition deadline elapsed") from exc

    def record_dispatch(self, request_id):
        audit.journal(self, "dispatch", request_id=request_id)


def configured_directory(line, attachment=None):
    cwd = line.get("cwd") or (attachment or {}).get("cwd")
    return str(Path(cwd)) if cwd else None
