"""Read workflow runs in the scope of their exact granted window."""

from fastapi import HTTPException

from .machine_scope import deny_unless
from .screen_grants import line_grants
from .screen_helper_updates import HelperUpdating
from .screen_workflow_evidence import authorized_window


def require_run_window(service, principal, row):
    grant, _ = authorized_window(service.hub, principal, row["grant_id"], row["conv_id"])
    if grant["owner_id"] != row["owner_id"]:
        raise HTTPException(409, "resume requires the original window grant")


def machine_can_start(service, principal, conv_id):
    try:
        service.start_identity(principal, conv_id)
        deny_unless(service.db, principal, conv_id, "write")
    except HTTPException:
        return False
    return True


def machine_run_participant(principal, row):
    ident = principal.attachment_id
    return ident is not None and ident in (row["attachment_id"], row["resume_attachment_id"])


def machine_can_see(service, principal, row):
    if machine_run_participant(principal, row):
        return True
    if not machine_can_start(service, principal, row["conv_id"]):
        return False
    try:
        require_run_window(service, principal, row)
    except (HTTPException, HelperUpdating):
        return False
    return True


def machine_listing(service, principal, conv_id):
    attachment_id = principal.attachment_id
    clause, args = "(attachment_id=? OR resume_attachment_id=?)", (attachment_id, attachment_id)
    if not machine_can_start(service, principal, conv_id):
        return clause, args
    windows = []
    for candidate in line_grants(service.db, conv_id):
        try:
            grant, _ = authorized_window(service.hub, principal, candidate["id"], conv_id)
        except (HTTPException, HelperUpdating):
            continue
        windows.append((grant["id"], grant["owner_id"]))
    if not windows:
        return clause, args
    pairs = ", ".join("(?,?)" for _ in windows)
    return f"({clause} OR (grant_id, owner_id) IN (VALUES {pairs}))", (
        *args, *(value for window in windows for value in window)
    )
