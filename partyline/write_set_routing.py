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


def machine_grant_error(db, principal, path: str, chain: list[str],
                        requester_id: str | None = None) -> str | None:
    """403 text when an ancestor captain may not grant ``path`` to a line under ``chain``.

    The captain must be the live lead of one of the line's strict ancestors (``chain``), must
    not be the requester, and the path must resolve inside a write grant the captain's own
    line holds or a writable entry of its own fence write set (checkout, Git carve-outs,
    `.review/`, `.scratch/`). Anything wider is a person's call. Shared by deciding a request
    and by create_task(write_set=...), which grants at creation with the same authority.
    """
    if docker_relay.is_docker_socket(path):
        return "docker access is root-equivalent; a person decides"
    if not principal.is_lead or principal.conv_id not in chain:
        return "outside your grants; a person decides"
    lead = lead_attachment(db, principal.conv_id)
    if (lead is None or lead["id"] != principal.attachment_id
            or lead["status"] not in ("starting", "running")):
        return "outside your grants; a person decides"
    if requester_id and requester_id == principal.attachment_id:
        return "outside your grants; a person decides"
    wanted = os.path.realpath(path)
    rows = db._exec(
        "SELECT path FROM conversation_write_grants WHERE conv_id=?",
        (principal.conv_id,)).fetchall()
    for row in rows:
        if _covers(row["path"], wanted):
            return None
    fence_workspaces.load(db, lead)
    for src, _dst, read_only in fence_paths.write_set(lead, create=False):
        if not read_only and _covers(src, wanted):
            return None
    return "outside your grants; a person decides"
