"""Named process traits on attach presets, plus conservative live matching."""

from __future__ import annotations

import json
import shlex
import time

TRAIT_FIELDS = (
    ("reads_images", "Reads images", False),
    ("can_manage", "Can manage a line", False),
    ("implements", "Fast implementer", True),
    ("emitter", "Emitter", False),
)
TRAIT_DEFAULTS = {name: default for name, _label, default in TRAIT_FIELDS}


def is_emitter(row: dict) -> bool:
    return row.get("adapter") == "raw" or bool(row.get("emitter"))


def coerce_traits(row: dict) -> dict[str, bool]:
    if is_emitter(row):
        return {name: name == "emitter" for name in TRAIT_DEFAULTS}
    return {
        name: default if row.get(name) is None else bool(row[name])
        for name, default in TRAIT_DEFAULTS.items()
    }


def requested_traits(adapter: str, supplied: dict, *, base: dict | None = None) -> dict[str, bool]:
    """Resolve omitted flags and validate explicit choices before persisting them."""
    if adapter == "raw":
        return coerce_traits({"adapter": adapter})
    flags = {**coerce_traits(base or {}), **supplied}
    if flags["emitter"]:
        conflicts = supplied if supplied.get("emitter") else flags
        if any(value for key, value in conflicts.items() if key != "emitter"):
            raise ValueError("Emitter cannot be combined with Reads images, Can manage a line, "
                             "or Fast implementer")
    return coerce_traits(flags)


def attachment_row(row):
    att = {**dict(row), "command": json.loads(row["command"])}
    if att.get("process_traits") is not None or att["adapter"] == "raw":
        att.update(coerce_traits({**json.loads(att.get("process_traits") or "{}"),
                                  "adapter": att["adapter"]}))
    return att


def attachment_traits(att: dict, matched: dict | None) -> dict[str, bool] | None:
    if is_emitter(att) or att.get("process_traits") is not None:
        return coerce_traits(att)
    if matched is not None and not is_emitter(matched):
        return coerce_traits(matched)
    return None


def coerce_preset(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {**row, **coerce_traits(row)}


def write_preset(db, preset_id, title, name, adapter, command, traits=None,
                 max_instances: int = 0, auto_compact_tokens: int = 0):
    flags = coerce_traits({**(traits or {}), "adapter": adapter})
    # db.save_preset passes every extra through **traits, so the declared
    # seat count and the compact threshold arrive there; the parameters stay
    # for direct callers.
    max_instances = int((traits or {}).get("max_instances") or max_instances)
    auto_compact_tokens = int(
        (traits or {}).get("auto_compact_tokens") or auto_compact_tokens)
    # None inherits the instance's compaction limit, and an explicit 0 turns
    # rotation off for this preset, so "or" would erase the one value that
    # means something.
    max_compactions = (traits or {}).get("max_compactions")
    ts = time.time()
    db._exec(
        "INSERT INTO presets(id,title,name,adapter,command,created_at,"
        "reads_images,can_manage,implements,max_instances,auto_compact_tokens,"
        "max_compactions,emitter) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET title=excluded.title, name=excluded.name,"
        " adapter=excluded.adapter, command=excluded.command,"
        " reads_images=excluded.reads_images, can_manage=excluded.can_manage,"
        " implements=excluded.implements, max_instances=excluded.max_instances,"
        " auto_compact_tokens=excluded.auto_compact_tokens,"
        " max_compactions=excluded.max_compactions, emitter=excluded.emitter",
        (
            preset_id, title, name, adapter, command, ts,
            int(flags["reads_images"]), int(flags["can_manage"]),
            int(flags["implements"]), int(max_instances), int(auto_compact_tokens),
            None if max_compactions is None else int(max_compactions), int(flags["emitter"]),
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
    A process spawned for a task carries a task-derived handle, so the preset
    it was staffed from is recorded on the row and matched instead.
    Two hits — say presets named both ``astra`` and ``astra-2`` — are
    ambiguous and match nothing, exactly like any other collision.
    """
    name = attachment["name"].lower()
    recorded = (attachment.get("preset") or "").lower()
    adapter = attachment["adapter"]
    command = list(attachment["command"])
    hits = []
    for preset in presets:
        argv = _command_argv(preset["command"])
        if argv is None:
            continue
        if (preset["adapter"] == adapter
                and (preset["name"].lower() == recorded if recorded
                     else _numbered_handle(name, preset["name"].lower()))
                and (argv == command or (recorded and
                     (not argv or attachment.get("model_override") is not None or
                      attachment.get("effort_override") is not None)))):
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
