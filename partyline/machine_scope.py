"""What a machine token may do on a line, given live lead/parent rows."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException

from .auth_guard import Principal
from .db import Db
from .hierarchy import child_ids, descendants, parent_id_of

Capability = Literal[
    "read",
    "write",
    "assign",
    "attach",
    "close",
    "create_child",
    "report",
    "notify",
    "read_reports",
    "appoint_lead",
    "archive",
    "link_parent",
]

ALL_CAPABILITIES: tuple[Capability, ...] = (
    "read",
    "write",
    "assign",
    "attach",
    "close",
    "create_child",
    "report",
    "notify",
    "read_reports",
    "appoint_lead",
    "archive",
    "link_parent",
)


def is_human(principal: Principal) -> bool:
    return principal.kind == "user"


def visible_conversation_ids(db: Db, principal: Principal) -> set[str] | None:
    """None means every line (humans). Machines see home plus descendants."""
    if is_human(principal):
        return None
    home = principal.conv_id
    if not home:
        return set()
    allowed = {home}
    if principal.is_lead:
        allowed.update(descendants(db, home))
    return allowed


def _home_lead_tree(db: Db, principal: Principal, conv_id: str) -> bool:
    if not principal.is_lead or not principal.conv_id:
        return False
    return conv_id == principal.conv_id or conv_id in descendants(db, principal.conv_id)


def allows(db: Db, principal: Principal, conv_id: str, capability: Capability) -> bool:
    if is_human(principal):
        return True
    if principal.kind != "machine" or not principal.conv_id:
        return False
    home = principal.conv_id
    conv = db.get_conversation(conv_id)
    if conv is None:
        return False
    if capability in ("archive", "link_parent"):
        return False
    if capability == "appoint_lead":
        return _home_lead_tree(db, principal, conv_id)
    if capability == "create_child":
        return principal.is_lead and conv_id == home
    if capability in ("report", "notify"):
        return principal.is_lead and conv_id == home and bool(parent_id_of(conv))
    if capability == "read_reports":
        return principal.is_lead and conv_id == home
    if conv_id == home:
        if capability in ("read", "write"):
            return True
        if capability in ("attach", "close", "assign"):
            return principal.is_lead
        return False
    if _home_lead_tree(db, principal, conv_id):
        return capability in ("read", "write", "assign", "attach", "close")
    return False


def allows_restart_plan(
    principal: Principal, conversation_id: str, *, db: Db | None = None, scope: str = "line"
) -> bool:
    """Host-local plan create: humans, or a machine whose home is the owner line.

    Cockpit ``plan LINE`` authenticates with ``PARTYLINE_TOKEN`` on loopback.
    That token may name only its own line as plan owner — no other admin
    surface, no descendant grant. Loopback is checked by the route.
    """
    if is_human(principal):
        return True
    owns_plan = (
        principal.kind == "machine"
        and bool(principal.attachment_id)
        and principal.conv_id == conversation_id
    )
    if not owns_plan or scope == "line":
        return owns_plan
    if scope != "all" or db is None or not principal.is_lead:
        return False
    # Never narrow "all": authorize every selected line or refuse the request.
    active_lines = [
        row["id"] for row in db.list_conversations()
        if any(att["status"] in ("starting", "running")
               for att in db.list_attachments(row["id"]))
    ]
    return all(allows(db, principal, conv_id, "close") for conv_id in active_lines)


def deny_unless(
    db: Db, principal: Principal, conv_id: str, capability: Capability
) -> None:
    conv = db.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(404)
    if not allows(db, principal, conv_id, capability):
        raise HTTPException(403, "this credential cannot act on that line")


def deny_archive_if_children(db: Db, conv_id: str) -> None:
    if child_ids(db, conv_id):
        raise HTTPException(409, "unlink or archive child lines first")


def deny_purge_if_parent_refs(db: Db, conv_id: str) -> None:
    if child_ids(db, conv_id):
        raise HTTPException(409, "unlink or purge child lines first")


def deny_unless_attachment(
    db: Db, principal: Principal, att_id: str, capability: Capability
) -> dict:
    att = db.get_attachment(att_id)
    if att is None:
        raise HTTPException(404)
    deny_unless(db, principal, att["conv_id"], capability)
    return att


def capability_state(db: Db, principal: Principal, conv_id: str | None = None) -> dict:
    """Role and actions from the same `allows()` the routes use."""
    target = conv_id or principal.conv_id
    if is_human(principal):
        role = "human"
    elif principal.is_lead:
        role = "lead"
    else:
        role = "implementer"
    actions = [
        cap
        for cap in ALL_CAPABILITIES
        if target and allows(db, principal, target, cap)
    ]
    home = db.get_conversation(principal.conv_id) if principal.conv_id else None
    return {
        "kind": principal.kind,
        "role": role,
        "conv_id": principal.conv_id,
        "attachment_id": principal.attachment_id,
        "is_lead": bool(principal.is_lead),
        "parent_id": parent_id_of(home),
        "target_conv_id": target,
        "actions": actions,
    }
