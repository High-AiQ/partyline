"""How many compactions a process may have before it is rotated to a fresh instance.

Each compaction is a lossy summary of the last one, so a process is allowed a
few and is then replaced by a fresh instance of itself, briefed from a short
hand-off note it wrote (`compaction_rotation`). The limit is one instance
setting with an optional override per preset. 0 turns rotation off entirely,
the thrash rule included: a thrashing process then only rings its captain, as
it did before the limit existed.
"""

from __future__ import annotations

SETTING = "max_compactions_per_process"
DEFAULT_LIMIT = 2
LIMIT_CEILING = 20


def clamp(value) -> int | None:
    """A stored or submitted limit as an int in range; None when it isn't one."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(0, min(LIMIT_CEILING, number))


def global_limit(db) -> int:
    try:
        stored = clamp(db.get_setting(SETTING))
    except AttributeError:  # a minimal db (the hook tests' fake) has no settings
        return 0
    return DEFAULT_LIMIT if stored is None else stored


def limit_for(db, att: dict) -> int:
    """This process's limit: its preset's override, else the instance setting.

    The preset is the unique match `attachment_preset` finds, so a task handle
    like ``impl-ab12`` resolves through the preset it was staffed from; an
    ambiguous or missing match falls back to the instance setting.
    """
    from .preset_roles import attachment_preset

    try:
        preset = attachment_preset(db, att)
    except AttributeError:
        preset = None
    override = clamp(preset.get("max_compactions")) if preset and \
        preset.get("max_compactions") is not None else None
    return global_limit(db) if override is None else override
