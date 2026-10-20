"""What a machine token may do on a line, given live lead/parent rows."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException

from .auth_guard import Principal
from .db import Db
from .hierarchy import child_ids, descendants, lead_attachment, parent_id_of
from .line_depth import (
    MAX_CAPTAIN_DEPTH, depth, has_captain, live_workers, may_split, sideways_attach_reason,
    staffed_split_reason,
)

Capability = Literal[
    "read",
    "write",
    "assign",
    "attach",
    "close",
    "accept",
    "create_child",
    "report",
    "notify",
    "read_reports",
    "appoint_lead",
    "archive",
    "link_parent",
    "create_task", "tasks", "restart_reviewer", "reopen_task", "request_review", "review_verdict", "blocked",
]

ALL_CAPABILITIES: tuple[Capability, ...] = (
    "read",
    "write",
    "assign",
    "attach",
    "close",
    "accept",
    "create_child",
    "report",
    "notify",
    "read_reports",
    "appoint_lead",
    "archive",
    "link_parent",
    "create_task", "tasks", "restart_reviewer", "reopen_task", "request_review", "review_verdict", "blocked",
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


def _live_lead(db: Db, conv_id: str) -> dict | None:
    """The manager row only while its process can actually run.

    A detached or exited lead keeps ``is_lead=1`` so resuming it restores the
    role. That stale flag must not be treated as a manager that could still be
    re-pointed: after the sole lead detaches, no machine satisfies
    ``_home_lead_tree``, so without this the line can never get a new manager
    except from a human.
    """
    lead = lead_attachment(db, conv_id)
    if lead is None or lead["status"] not in ("starting", "running"):
        return None
    return lead


def allows(db: Db, principal: Principal, conv_id: str, capability: Capability) -> bool:
    if is_human(principal):
        return True
    if principal.kind != "machine" or not principal.conv_id:
        return False
    home = principal.conv_id
    conv = db.get_conversation(conv_id)
    if conv is None:
        return False
    from .orchestrator_store import task, task_actions
    task_row = task(db, conv_id)
    if capability in ("request_review", "review_verdict", "blocked"):
        if (capability == "review_verdict" and conv_id == home and principal.is_lead
                and conv.get('captain_mode', 'manager_tree') == 'orchestrator'):
            return True
        return capability in task_actions(db, principal, conv_id)
    if capability in ("create_task", "tasks", "restart_reviewer", "reopen_task"):
        return (conv_id == home and principal.is_lead and conv['parent_id'] is None
                and conv.get('captain_mode', 'manager_tree') == 'orchestrator')
    if task_row and capability == "archive" and not (
            principal.is_lead and home == task_row["root_id"] and conv_id != home):
        return False
    if task_row and capability in ("attach", "appoint_lead", "create_child", "report", "notify"):
        return False
    if capability == "archive":
        # A captain may retire a descendant line it accepted, never itself or
        # a line outside its tree: `deny_unless` and the route's situational
        # checks (no live processes, goal cleared, worktree SAFE) gate the rest.
        return conv_id != home and _home_lead_tree(db, principal, conv_id)
    if capability == "accept":
        # Recording a hand-off: the parent's captain accepting a child's work,
        # or the line's own captain marking hand-off. A captain higher up
        # reviews the work again at its own scope; nobody accepts across two
        # levels, and a captain cannot accept its parent's branch either.
        parent = parent_id_of(conv)
        return principal.is_lead and home in (conv_id, parent or "")
    if capability == "link_parent":
        return False
    if capability == "appoint_lead":
        # Deterministic only: a person, or a captain over this line. There is no
        # natural-language handoff — a line with no captain waits for a person.
        return _home_lead_tree(db, principal, conv_id)
    if capability == "create_child":
        # People are never boxed by the depth cap; machines stop at it, and a
        # machine whose line already carries workers assigns them instead.
        return principal.is_lead and conv_id == home and may_split(db, home)
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


def sibling_messaging(db: Db, principal: Principal, conv_id: str) -> bool:
    """A captain may post a message to a sibling line — messages only (5.11).

    Two captains cut from one parent coordinate constantly, and every such
    post used to bounce off the assign check: a sibling is neither the
    captain's own line nor a descendant of it. Both lines must share the
    same **non-null** parent, so a root line or a cousin never qualifies,
    and no other capability rides along — attach, accept, archive and the
    rest stay exactly as refused as they were.
    """
    if principal.kind != "machine" or not principal.is_lead or not principal.conv_id:
        return False
    home = principal.conv_id
    if home == conv_id:
        return False  # own line: already allowed by "write"
    target = db.get_conversation(conv_id)
    parent = parent_id_of(target) if target else None
    if parent is None:
        return False
    return parent == parent_id_of(db.get_conversation(home))


def allows_restart_plan(
    principal: Principal, conversation_id: str, *, db: Db | None = None, scope: str = "line"
) -> bool:
    """Host-local plan create: humans, or a machine whose home is the owner line.

    A machine authenticates with ``PARTYLINE_TOKEN`` on loopback to plan its
    own line. That token may name only its own line as plan owner — no other
    admin surface, no descendant grant. Loopback is checked by the route.
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
    if (conv_id in getattr(db, "retiring_lines", set())
            and capability in ("attach", "create_child", "accept", "assign", "write", "appoint_lead",
                               "link_parent")):
        raise HTTPException(409, "retirement is in progress; this line cannot change")


def parallel_worker_reason(db: Db, conv_id: str) -> bool:
    """Whether a new attachment would be a second implementer on a captained line.

    Finding 2.14: two workers on one line share one branch, commit
    interleaved, and the hand-off is all-or-nothing — parallel slices mean
    parallel lines.
    """
    return has_captain(db, conv_id) and bool(live_workers(db, conv_id))


PARALLEL_WORKERS_REFUSAL = (
    "parallel slices mean parallel lines: this line has a captain and a live worker, and "
    "one branch accepts all-or-nothing — give the new slice its own line with POST "
    "…/children, pass {\"allow_shared_branch\": true} to share the branch anyway — or, to "
    "replace a worker, close the old one first (DELETE /api/attachments/<id>)")


def deny_sideways_attach(db: Db, principal: Principal, conv_id: str) -> None:
    """A machine staffs child lines, not a line that already has them."""
    if is_human(principal):
        return
    reason = sideways_attach_reason(db, conv_id)
    if reason:
        raise HTTPException(403, reason)


def deny_staffed_split(db: Db, principal: Principal, conv_id: str) -> None:
    """A machine assigns the workers on its line; it does not split around them."""
    if is_human(principal):
        return
    reason = staffed_split_reason(db, conv_id)
    if reason:
        raise HTTPException(403, reason)


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
    from .orchestrator_store import task
    task_row = task(db, principal.conv_id) if principal.conv_id else None
    if task_row and task_row["reviewer_id"] == principal.attachment_id:
        role = "reviewer"
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
        "depth": depth(db, target) if target and db.get_conversation(target) else 0,
        "max_depth": MAX_CAPTAIN_DEPTH,
    }
