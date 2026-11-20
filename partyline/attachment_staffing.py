"""Resolve trusted presets and effective traits for the public attach route."""

import shlex

from fastapi import HTTPException

from .machine_scope import is_human
from .preset_overrides import attachment_command
from .preset_roles import attachment_preset, named_preset, require_attachment_role, require_role
from .preset_traits import TRAIT_DEFAULTS, coerce_traits, requested_traits


def resolve_command(db, body):
    command, selected = attachment_command(db, body)
    if selected is None and body.preset_name:
        selected = named_preset(db, body.preset_name)
        if not command:
            command = selected["command"]
    return command, selected


def resolve_staffing(db, body, principal, command, selected, default_command):
    candidate = {"name": body.name, "adapter": body.adapter, "command": command}
    match = selected or attachment_preset(db, candidate)
    if match and match["adapter"] != body.adapter:
        raise HTTPException(400, f"preset '{match['name']}' does not match the adapter")
    if match is None and not body.command:
        # A blank command on a preset requests the registered adapter default.
        presets = [dict(row, command=row["command"] or shlex.join(default_command))
                   for row in db.list_presets()]
        match = attachment_preset(db, candidate, presets)

    supplied = {key: getattr(body, key) for key in TRAIT_DEFAULTS if key in body.model_fields_set}
    person = is_human(principal)
    if person:
        try:
            traits = requested_traits(body.adapter, supplied, base=match)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        if supplied:
            raise HTTPException(403, "only a person can set process traits")
        traits = coerce_traits({**(match or {}), "adapter": body.adapter})

    explicit_role = "staffing_role" in body.model_fields_set
    role = ("captain" if body.successor else "emitter" if traits["emitter"] and not explicit_role
            else body.staffing_role)
    if traits["emitter"] != (role == "emitter") or (body.successor and body.staffing_role == "emitter"):
        raise HTTPException(403, "Emitter processes use the emitter role and cannot staff work or lead")

    if selected and body.model is None and body.effort is None:
        try:
            expected = shlex.split(selected["command"]) or default_command
        except ValueError:
            expected = None
        if expected != command:
            raise HTTPException(400, f"preset '{selected['name']}' does not match the command")

    if not person:
        if match is None:
            require_attachment_role(db, candidate, role)
        selected = require_role(match, role)
    return role, traits, selected
