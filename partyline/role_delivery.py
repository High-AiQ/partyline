"""Refresh manager knowledge from live permissions without waking a process."""

from typing import NamedTuple

from .role_briefing import role_instructions


class RoleState(NamedTuple):
    role: str
    conv_id: str
    parent_id: str | None
    actions: tuple[str, ...]


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
    return RoleState(state.role, att["conv_id"], state.parent_id, tuple(state.actions))


def bind_role_delivery(db, att: dict) -> None:
    initial = current_role(db, att["id"])
    att["role_briefing"] = role_instructions(initial.actions, initial.conv_id, initial.parent_id)
    original_rider = att["digest_rider"]
    previous = None if att.get("resume") else initial

    def rider() -> str:
        nonlocal previous
        current = current_role(db, att["id"])
        update = ""
        if current != previous:
            previous = current
            if current.role == "lead":
                update = role_instructions(current.actions, current.conv_id, current.parent_id)
            else:
                update = "Your current role is ordinary participant. Use only your own line's tools."
        return "\n".join(part for part in (original_rider(), update) if part)

    att["digest_rider"] = rider
