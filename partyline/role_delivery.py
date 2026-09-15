"""Refresh manager knowledge from live permissions without waking a process."""

from typing import NamedTuple

from .goal import goal_rider
from .line_depth import depth as line_depth, staffed_split_reason
from .role_briefing import role_instructions
from .staffing import staffing_line


class RoleState(NamedTuple):
    role: str
    conv_id: str
    parent_id: str | None
    actions: tuple[str, ...]
    depth: int = 0
    staffed: bool = False


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
                     staffed_split_reason(db, att["conv_id"]) is not None)


def bind_role_delivery(db, att: dict) -> None:
    initial = current_role(db, att["id"])
    att["role_briefing"] = role_instructions(
        initial.actions, initial.conv_id, initial.parent_id, initial.depth, initial.staffed)
    original_rider = att["digest_rider"]
    previous = None if att.get("resume") else initial

    def rider() -> str:
        nonlocal previous
        current = current_role(db, att["id"])
        update = ""
        if current != previous:
            previous = current
            update = role_instructions(
                current.actions, current.conv_id, current.parent_id, current.depth,
                current.staffed)
            if not update:
                update = ("Your current role is ordinary participant, not captain. "
                          "Use only your own line's tools.")
        goal = staffing = ""
        if current.role == "lead":
            goal = goal_rider(db, current.conv_id)
            staffing = staffing_line(db, current.conv_id)
        return "\n".join(part for part in (original_rider(), goal, staffing, update) if part)

    att["digest_rider"] = rider
