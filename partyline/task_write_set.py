"""Pre-granting write scope when a task is created.

A task that needs six paths used to stall six times: one request per path, each waiting for
its own decision. A captain that knows the paths grants them with ``create_task(write_set=[...])``
before the implementer starts. Validation and authority are those of approving a request
(``write_set_requests.validate_grantable``, ``write_set_routing.machine_grant_error``).
"""

from fastapi import HTTPException

from .hierarchy import ancestors
from .machine_scope import is_human
from .system_notice import post_system_notice
from .write_set_requests import validate_grantable
from .write_set_routes import add_write_grant
from .write_set_routing import machine_grant_error


def check(db, actor, root_id: str, paths: list[str]) -> list[str]:
    """The grantable, deduplicated paths, or the refusal naming every one that was not granted."""
    paths = list(dict.fromkeys(validate_grantable(db, path) for path in paths))
    if not is_human(actor):
        chain = [root_id, *ancestors(db, root_id)]
        refused = [path for path in paths if machine_grant_error(db, actor, path, chain)]
        if refused:
            named = ", ".join(f"`{path}`" for path in refused)
            raise HTTPException(
                403, f"none of these paths were granted: {named}; a captain grants only inside its "
                     "own grants or checkout, anything wider is a person's decision (file a "
                     "write-set request after creating the task)")
    return paths


async def grant(runtime, actor, conv_id: str, paths: list[str]) -> None:
    for path in paths:
        add_write_grant(runtime.db, conv_id, path, actor.name)
    listed = ", ".join(f"`{path}`" for path in paths)
    await post_system_notice(runtime, conv_id, f"☏ write-set grant for {listed} by @{actor.name} "
                             "at task creation", actor=actor)
