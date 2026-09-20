"""Refresh manager knowledge from live permissions without waking a process."""

from typing import NamedTuple

from .goal import goal_rider
from .accept_sha import handoff_rider
from .line_depth import depth as line_depth, has_captain, staffed_split_reason
from .role_briefing import WORKER_REMINDER, role_instructions, worker_instructions
from .staffing import staffing_line


class RoleState(NamedTuple):
    role: str
    conv_id: str
    parent_id: str | None
    actions: tuple[str, ...]
    depth: int = 0
    staffed: bool = False
    captained: bool = False


def current_role(db, attachment_id: str) -> RoleState:
    from .auth_guard import Principal
    from .hierarchy_contracts import CapabilityState
    from .machine_scope import capability_state

    att = db.get_attachment(attachment_id)
    if att is None:
        raise ValueError("attachment no longer exists")
    principal = Principal(kind="machine", name=att["name"], conv_id=att["conv_id"],
                          attachment_id=att["id"], is_lead=bool(att.get("is_lead")))
    state = CapabilityState.model_validate(capability_state(db, principal))
    return RoleState(state.role, att["conv_id"], state.parent_id, tuple(state.actions),
                     line_depth(db, att["conv_id"]),
                     staffed_split_reason(db, att["conv_id"]) is not None,
                     has_captain(db, att["conv_id"]))


def _instructions(state: RoleState) -> str:
    """The pack for a state: the captain's, else the worker's when a captain is live."""
    return role_instructions(
        state.actions, state.conv_id, state.parent_id, state.depth, state.staffed
    ) or worker_instructions(state.captained)


def briefing_pointer(conv_id: str) -> str:
    return f"(captain pack: GET /api/conversations/{conv_id}/briefing)"


def bind_role_delivery(db, att: dict) -> None:
    initial = current_role(db, att["id"])
    att["role_briefing"] = _instructions(initial)
    original_rider = att["digest_rider"]
    previous = None if att.get("resume") else initial
    last_goal = last_staffing = last_handoff = None
    worker_reminder_sent = False

    def rider() -> str:
        nonlocal previous, last_goal, last_staffing, last_handoff, worker_reminder_sent
        current = current_role(db, att["id"])
        update = ""
        captain_transition = previous is None or (
            (previous.role == "lead") != (current.role == "lead")
        )
        worker_transition = previous is None or previous.captained != current.captained
        worker_now = current.role != "lead" and current.captained
        worker_was = previous is not None and previous.role != "lead" and previous.captained
        if current.role != "lead":
            last_goal = last_staffing = last_handoff = None
        if current != previous:
            demoted = previous is not None and previous.role == "lead" and current.role != "lead"
            previous = current
            if captain_transition or (worker_now and worker_transition):
                update = _instructions(current)
            if demoted and update:
                update += ("\nYour current role is ordinary participant, not captain. "
                           "Use only your own line's tools.")
            elif not update and (demoted or (worker_was and not worker_now)):
                update = ("Your current role is ordinary participant, not captain. "
                          "Use only your own line's tools.")
        goal = staffing = handoff = worker = pointer = ""
        if current.role == "lead":
            current_goal = goal_rider(db, current.conv_id)
            current_staffing = staffing_line(db, current.conv_id)
            current_handoff = handoff_rider(db, current.conv_id)
            goal = _delta(current_goal, last_goal, "goal")
            staffing = _delta(current_staffing, last_staffing, "staffing")
            handoff = _delta(current_handoff, last_handoff, "hand-offs")
            last_goal, last_staffing, last_handoff = (
                current_goal, current_staffing, current_handoff)
            if not captain_transition:
                pointer = briefing_pointer(current.conv_id)
        elif current.captained:
            if not worker_reminder_sent or (worker_now and not worker_was):
                worker = WORKER_REMINDER
            worker_reminder_sent = True
        else:
            worker_reminder_sent = False
        return "\n".join(
            part for part in (original_rider(), goal, staffing, handoff, update, worker, pointer)
            if part)

    att["digest_rider"] = rider


def _delta(value: str, previous: str | None, label: str) -> str:
    if value == previous:
        return ""
    if value:
        return value
    return f"({label} cleared)" if previous else ""
