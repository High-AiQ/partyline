"""Whether a memory warning still describes the process's current budget."""

from __future__ import annotations

from .resource_budget import cap_bytes, settings


def warning_still_crosses(runtime, target: dict, queued_cap: int) -> bool:
    """False once the cap changed, or the latest sample no longer crosses the threshold."""
    from .memory_sampler import crosses_warning, warning_limit
    config = settings(runtime.db)
    cap = cap_bytes(target, config)
    if cap != queued_cap:
        return False
    sample = runtime.memory_usage.get(target["id"])
    return sample is None or crosses_warning(
        sample["usage_bytes"], warning_limit(cap), config["memory_warn_percent"])
