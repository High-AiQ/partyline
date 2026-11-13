"""Captain and worker instructions, selected from live capabilities."""

from collections.abc import Collection

from .pack_blocks import ORCHESTRATOR
from .worker_pack import WORKER_REMINDER, worker_instructions  # noqa: F401


def role_instructions(
    actions: Collection[str], conv_id: str, parent_id: str | None, depth: int = 0,
    staffed: bool = False,
) -> str:
    """Give every appointed captain the orchestrator pack."""
    return "\n\n" + ORCHESTRATOR if "assign" in actions else ""
