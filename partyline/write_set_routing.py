"""Find an ancestor captain whose existing write scope covers a request."""

import os

from . import docker_relay, fence_paths, fence_workspaces
from .hierarchy import ancestors, lead_attachment


def _covers(base: str, path: str) -> bool:
    base, path = os.path.realpath(base), os.path.realpath(path)
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def eligible_captain(db, conv_id: str, paths: list[str], requester_id: str | None) -> dict | None:
    """Return the nearest live ancestor lead able to decide every path."""
    chain = ancestors(db, conv_id)
    if not chain or any(docker_relay.is_docker_socket(path) for path in paths):
        return None
    for captain_conv_id in chain:
        lead = lead_attachment(db, captain_conv_id)
        if (lead is None or lead["status"] not in ("starting", "running")
                or lead["id"] == requester_id):
            continue
        grants = db._exec(
            "SELECT path FROM conversation_write_grants WHERE conv_id=?", (captain_conv_id,)
        ).fetchall()
        bases = [row["path"] for row in grants]
        try:
            fence_workspaces.load(db, lead)
            writable = (src for src, _dst, read_only in fence_paths.write_set(lead, create=False)
                        if not read_only)
            bases.extend(writable)
        except Exception:
            continue
        if all(any(_covers(base, path) for base in bases) for path in paths):
            return lead
    return None
