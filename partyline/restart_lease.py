"""Recoverable cross-process ownership for automatic restart plans."""

from __future__ import annotations

import asyncio
import uuid
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from .db import Db, RestartPlan
from .file_events import FileEvents

T = TypeVar("T")
LeaseGuard = Callable[[], None]
PlanOperation = Callable[[RestartPlan, LeaseGuard], Awaitable[T]]


@dataclass(frozen=True)
class LeaseTiming:
    lease_seconds: float = 15.0
    renew_interval: float = 5.0
    retry_interval: float = 0.25


DEFAULT_LEASE_TIMING = LeaseTiming()


class RestartPlanLeaseLost(RuntimeError):
    """Another server generation now owns the automatic restart plan."""


async def _claim(db: Db, owner: str, timing: LeaseTiming) -> RestartPlan | None:
    async with FileEvents(db.path) as events:
        while True:
            pending = db.get_restart_plan()
            if pending is None or pending["mode"] != "automatic":
                return None
            claimed = db.claim_restart_plan("automatic", owner, timing.lease_seconds)
            if claimed is not None:
                return claimed
            # no-poll (b): the current owner's persisted lease expiry is a deadline.
            remaining = max(0, (pending.get('claim_until') or 0) - time.time())
            try:
                await asyncio.wait_for(events.wait(asyncio.current_task()), remaining)
            except TimeoutError:
                pass


async def _renew(db: Db, plan: RestartPlan, owner: str, timing: LeaseTiming) -> None:
    while True:
        # no-poll (c): ownership protocol lease renewal; no state discovery
        await asyncio.sleep(timing.renew_interval)
        if not db.renew_restart_plan_claim(plan["token"], owner, timing.lease_seconds):
            raise RestartPlanLeaseLost(
                "automatic reattachment lost its durable lease; the sequence was stopped "
                "and the plan was preserved for its current owner"
            )


async def run_automatic_restart_plan(
    db: Db,
    operation: PlanOperation[T],
    timing: LeaseTiming = DEFAULT_LEASE_TIMING,
) -> T | None:
    """Run one automatic plan under a renewable, crash-reclaimable DB lease."""
    owner = str(uuid.uuid4())
    plan = await _claim(db, owner, timing)
    if plan is None:
        return None

    def ensure_owned() -> None:
        if not db.renew_restart_plan_claim(plan["token"], owner, timing.lease_seconds):
            raise RestartPlanLeaseLost(
                "automatic reattachment lost its durable lease before the next process; "
                "the sequence was stopped and the plan was preserved"
            )

    operation_task = asyncio.create_task(operation(plan, ensure_owned))
    renewal_task = asyncio.create_task(_renew(db, plan, owner, timing))
    completed = False
    try:
        done, _ = await asyncio.wait(
            (operation_task, renewal_task), return_when=asyncio.FIRST_COMPLETED
        )
        if renewal_task in done:
            error = renewal_task.exception()
            raise error or RestartPlanLeaseLost("automatic reattachment lease ended unexpectedly")

        result = await operation_task
        if not db.complete_restart_plan(plan["token"], owner):
            raise RestartPlanLeaseLost(
                "automatic reattachment finished after losing its durable lease; "
                "the plan was preserved rather than reporting false completion"
            )
        completed = True
        return result
    finally:
        for task in (operation_task, renewal_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation_task, renewal_task, return_exceptions=True)
        if not completed:
            db.release_restart_plan_claim(plan["token"], owner)
