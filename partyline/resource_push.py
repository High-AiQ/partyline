"""Build the fleet resource snapshot carried by event-driven pushes."""

from .resource_budget import memory_ceiling, snapshot


def _view(runtime) -> dict:
    """The same body ``GET /api/resources`` returns."""
    return {**snapshot(runtime.db, None, runtime), "memory_ceiling_bytes": memory_ceiling()}
