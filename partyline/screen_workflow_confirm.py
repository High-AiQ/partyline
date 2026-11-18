"""Single-use human confirmation bound to a run's step and screen evidence."""

import asyncio
import secrets
from dataclasses import dataclass

from fastapi import HTTPException

from . import screen_workflow_audit as audit
from .screen_workflow_evidence import StopWorkflow

CONFIRM_SECONDS = 120


@dataclass
class Confirmation:
    token: str
    future: asyncio.Future
    step: object
    version: int
    deadline: float


class ConfirmationStops:
    async def confirm(self, step, tree, node):
        if not tree.live_events:
            raise StopWorkflow("confirmation requires a live event feed")
        cursor = self.changes.version
        future = asyncio.get_running_loop().create_future()
        deadline = self.service.clock() + CONFIRM_SECONDS
        self.confirmation = Confirmation(secrets.token_urlsafe(24), future, step, cursor, deadline)
        audit.change(self, "awaiting_confirmation")
        audit.event(self, "confirmation_requested")
        try:
            async with self.service.timeout_at(deadline):
                await self.service.push_changed(self)
                await self.post("waiting for human confirmation in chat.", wake_starter=True)
                decision = await self.confirmation_result(future, cursor)
        except TimeoutError as exc:
            raise StopWorkflow("confirmation expired", "stopped") from exc
        finally:
            self.confirmation = None
        if not decision:
            raise StopWorkflow("confirmation denied", "stopped")
        current = await self.observe(step)
        if current is None or self.changes.version != cursor or current.event_counter != tree.event_counter:
            raise StopWorkflow("confirmation expired after a screen change", "stopped")
        target = self.target(current, step)
        if target.helper != node.helper or target.cached.get("action_token") != node.cached.get(
            "action_token"
        ):
            raise StopWorkflow("confirmation target changed", "stopped")
        audit.change(self, "running")
        await self.service.push_changed(self)
        return current, target

    async def confirmation_result(self, future, cursor):
        changed = asyncio.create_task(self.changes.wait_after(cursor))
        try:
            await asyncio.wait((future, changed), return_when=asyncio.FIRST_COMPLETED)
            if self.changes.version != cursor:
                raise StopWorkflow("confirmation expired after a screen change", "stopped")
            return future.result()
        finally:
            changed.cancel()

    def confirmation_view(self):
        current = self.confirmation
        if not current or self.reason or current.future.done() or current.version != self.changes.version:
            return None
        remaining = current.deadline - self.service.clock()
        if remaining <= 0:
            return None
        step = current.step
        inputs = step.inputs.model_dump(exclude_none=True)
        if "files" in inputs:
            inputs = {"file_count": len(inputs["files"])}
        return {
            "token": current.token,
            "effect": step.effect,
            "remaining_seconds": remaining,
            "action": step.action,
            "target": step.target.model_dump(exclude_none=True),
            "inputs": inputs,
        }

    def decide(self, token, allowed, user_id):
        current = self.confirmation
        if not self.confirmation_view() or not secrets.compare_digest(token, current.token):
            raise HTTPException(409, "confirmation is stale or already used")
        self.authorize()
        self.require_current()
        audit.event(self, "confirmation_accepted" if allowed else "confirmation_denied", actor_id=user_id)
        current.future.set_result(allowed)
