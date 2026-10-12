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


def write_preset(db, preset_id, title, name, adapter, command, traits=None,
                 max_instances: int = 0, auto_compact_tokens: int = 0):
    flags = coerce_traits(traits or {})
    # db.save_preset passes every extra through **traits, so the declared
    # seat count and the compact threshold arrive there; the parameters stay
    # for direct callers.
    max_instances = int((traits or {}).get("max_instances") or max_instances)
    auto_compact_tokens = int(
        (traits or {}).get("auto_compact_tokens") or auto_compact_tokens)
    ts = time.time()
    db._exec(
        "INSERT INTO presets(id,title,name,adapter,command,created_at,"
        "reads_images,can_manage,implements,max_instances,auto_compact_tokens)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET title=excluded.title, name=excluded.name,"
        " adapter=excluded.adapter, command=excluded.command,"
        " reads_images=excluded.reads_images, can_manage=excluded.can_manage,"
        " implements=excluded.implements, max_instances=excluded.max_instances,"
        " auto_compact_tokens=excluded.auto_compact_tokens",
        (
            preset_id, title, name, adapter, command, ts,
            int(flags["reads_images"]), int(flags["can_manage"]),
            int(flags["implements"]), int(max_instances), int(auto_compact_tokens),
        ),
    )
    return coerce_preset(db.get_preset(preset_id))


def _command_argv(command: str) -> list[str] | None:
    try:
        return shlex.split(command)
    except ValueError:
        return None  # unclosed quotes and the like are not a match


def _numbered_handle(handle: str, base: str) -> bool:
    """Whether ``handle`` is ``base`` or a numbered instance of it (``base-2``)."""
    if handle == base:
        return True
    return handle.startswith(base + "-") and handle[len(base) + 1:].isdigit()


def match_preset(attachment: dict, presets: list[dict]) -> dict | None:
    """Return the preset only when handle, adapter, and command agree uniquely.

    A numbered handle (``astra-2``, as ``unique_handle`` suffixes it) matches
    its base preset, so a preset's live instances are counted, not hidden.
    Two hits — say presets named both ``astra`` and ``astra-2`` — are
    ambiguous and match nothing, exactly like any other collision.
    """
    name = attachment["name"].lower()
    adapter = attachment["adapter"]
    command = list(attachment["command"])
    hits = []
    for preset in presets:
        argv = _command_argv(preset["command"])
        if argv is None:
            continue
        if (preset["adapter"] == adapter
                and _numbered_handle(name, preset["name"].lower())
                and argv == command):
            hits.append(preset)
    return hits[0] if len(hits) == 1 else None


def auto_compact_tokens_for(db, att: dict) -> int:
    """The auto-compact threshold this attachment's preset declares.

    Resolved at spawn (and at every start, so a resume re-reads it) by
    matching the attachment against the preset catalog — the same unique
    match the staffing line uses. No preset, an ambiguous match, or a
    minimal db all answer 0: the CLI's own tuned default applies, which is
    exactly the behaviour of a fleet with no thresholds set.
    """
    try:
        presets = [p for p in (coerce_preset(row) for row in db.list_presets()) if p]
    except AttributeError:
        return 0
    matched = match_preset(att, presets)
    return int((matched or {}).get("auto_compact_tokens") or 0)
