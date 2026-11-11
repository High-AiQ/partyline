"""Apply advisory memory policy to event-triggered, single-read snapshots."""

import asyncio
import logging
import time

from .attachment_tmp import attachment_tmp_dir
from .browser_snapshots import push_resources
from .cgroup_sample import reclaim_scope
from .legacy_tmp import reap_pytest_if_tmpfs
from .memory_contracts import MemoryUsageEvent
from .memory_sampler import _warn, crosses_warning, warning_limit
from .memory_snapshot import refresh
from .resource_budget import live_rows, settings

REARM_RATIO = 0.65
NOTICE_WINDOW = 600.0
HOUSEKEEPING_BACKOFF = 60.0
logger = logging.getLogger(__name__)


async def _housekeeping(fn, *args):
    try:
        await asyncio.to_thread(fn, *args)
    except Exception:
        logger.exception("memory event housekeeping failed")


class MemoryPolicy:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.armed = {}
        self.over = {}
        self.activation = {}
        self.notified = {}
        self.housekeeping = {}
        self.reclaimed = {}

    def prune(self, live_ids):
        for state in (self.armed, self.over, self.activation, self.notified,
                      self.housekeeping, self.reclaimed):
            for ident in state.keys() - live_ids:
                state.pop(ident, None)

    async def handle(self, runtime, targets, warning):
        """Read once after a notification, publish, and warn the relevant processes."""
        fresh = await refresh(runtime)
        rows = live_rows(runtime.db)
        self.prune({row["id"] for row in rows})
        config = settings(runtime.db)
        for row in rows:
            ident = row["id"]
            if ident not in fresh or (targets is not None and ident not in targets):
                continue
            adapter = runtime.live.get(ident)
            if adapter is None:
                continue
            if self.activation.get(ident) is not adapter:
                for state in (self.armed, self.over, self.notified):
                    state.pop(ident, None)
                self.activation[ident] = adapter
            sample = runtime.memory_usage.get(ident)
            if sample is None:
                continue
            usage, raw, cap = sample["usage_bytes"], sample["raw_bytes"], sample["cap_bytes"]
            effective = warning_limit(cap)
            detail = sample.get("cgroup")
            now = self.clock()
            if detail and crosses_warning(usage, effective, config["memory_warn_percent"]) \
                    and now - self.housekeeping.get(ident, -HOUSEKEEPING_BACKOFF) >= HOUSEKEEPING_BACKOFF:
                self.housekeeping[ident] = now
                await _housekeeping(reap_pytest_if_tmpfs, attachment_tmp_dir(ident))
            if detail and usage < effective \
                    and crosses_warning(raw, effective, config["memory_warn_percent"]) \
                    and now - self.reclaimed.get(ident, -HOUSEKEEPING_BACKOFF) >= HOUSEKEEPING_BACKOFF:
                self.reclaimed[ident] = now
                await _housekeeping(reclaim_scope, detail["root"], raw - usage)
            if runtime.live.get(ident) is not adapter:
                continue
            if usage < effective * REARM_RATIO:
                self.armed[ident], self.over[ident] = True, False
            warn_here = warning is True or isinstance(warning, set) and ident in warning
            crossed = warn_here and usage >= effective > 0 and not self.over.get(ident)
            eligible = warn_here and crosses_warning(usage, effective, config["memory_warn_percent"]) \
                and self.armed.get(ident, True) \
                and now - self.notified.get(ident, -NOTICE_WINDOW) >= NOTICE_WINDOW
            if crossed or eligible:
                sample["pressure_notice"] = True
                current = runtime.memory_usage.get(ident)
                if current is not None:
                    current["pressure_notice"] = True
                delivering = getattr(runtime, "memory_pressure_delivering", None)
                if delivering is None:
                    delivering = runtime.memory_pressure_delivering = set()
                delivering.add(ident)
                try:
                    await _warn(runtime, row, usage, cap, shmem=(detail or {}).get("shmem", 0), sample=detail)
                except Exception:
                    sample.pop("pressure_notice", None)
                    if current is not None:
                        current.pop("pressure_notice", None)
                    runtime.memory_usage.get(ident, {}).pop("pressure_notice", None)
                    logger.exception("memory warning failed for %s", ident)
                else:
                    self.armed[ident], self.notified[ident] = False, now
                    if crossed:
                        self.over[ident] = True
                finally:
                    delivering.discard(ident)
            if runtime.live.get(ident) is not adapter:
                continue
            await runtime.broadcast(row["conv_id"], MemoryUsageEvent(
                attachment_id=ident, usage_bytes=usage, cap_bytes=cap, raw_bytes=raw,
                anon_bytes=sample.get("anon_bytes"), file_bytes=sample.get("file_bytes"),
                kernel_bytes=sample.get("kernel_bytes"), percent=sample["percent"],
            ))
        if any(getattr(runtime, "sockets", {}).values()):
            await push_resources(runtime)
