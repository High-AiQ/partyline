"""Named process traits on attach presets, plus conservative live matching."""

from __future__ import annotations

import shlex
import time

TRAIT_FIELDS = (
    ("reads_images", "Reads images", False),
    ("can_manage", "Can manage a line", False),
    ("implements", "Fast implementer", True),
)
TRAIT_DEFAULTS = {name: default for name, _label, default in TRAIT_FIELDS}


def coerce_traits(row: dict) -> dict[str, bool]:
    return {
        name: TRAIT_DEFAULTS[name] if row.get(name) is None else bool(row[name])
        for name, _label, _default in TRAIT_FIELDS
    }


def coerce_preset(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {**row, **coerce_traits(row)}


def write_preset(db, preset_id, title, name, adapter, command, traits=None):
    flags = coerce_traits(traits or {})
    ts = time.time()
    db._exec(
        "INSERT INTO presets(id,title,name,adapter,command,created_at,"
        "reads_images,can_manage,implements) VALUES(?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET title=excluded.title, name=excluded.name,"
        " adapter=excluded.adapter, command=excluded.command,"
        " reads_images=excluded.reads_images, can_manage=excluded.can_manage,"
        " implements=excluded.implements",
        (
            preset_id, title, name, adapter, command, ts,
            int(flags["reads_images"]), int(flags["can_manage"]),
            int(flags["implements"]),
        ),
    )
    return coerce_preset(db.get_preset(preset_id))


def _command_argv(command: str) -> list[str] | None:
    try:
        return shlex.split(command)
    except ValueError:
        return None  # unclosed quotes and the like are not a match


def match_preset(attachment: dict, presets: list[dict]) -> dict | None:
    """Return the preset only when handle, adapter, and command agree uniquely."""
    name = attachment["name"].lower()
    adapter = attachment["adapter"]
    command = list(attachment["command"])
    hits = []
    for preset in presets:
        argv = _command_argv(preset["command"])
        if argv is None:
            continue
        if (preset["adapter"] == adapter and preset["name"].lower() == name
                and argv == command):
            hits.append(preset)
    return hits[0] if len(hits) == 1 else None
