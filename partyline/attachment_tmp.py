"""Per-attachment temp directories (finding 5.12).

Every spawned process gets its own ``TMPDIR`` under a partyline-owned base,
so one line's engine runs, frames and wheels can neither collide with
another line's artifacts nor hide from reaping. The base is
``$PARTYLINE_TMP_BASE`` when set (tests pin it to their sandbox so nothing
touches the real ``/tmp``; production uses the platform temp), then
``partyline``, then one directory per attachment id, private (0700).

Reaping happens only at the moments an attachment ends: a person- or
captain-called close (``DELETE /api/attachments/<id>``), record removal, a
line archive, or a purge — the same moments Greg's finding names. A
restart-driven detach keeps the directory: the same id always resumes into
the same path, and no CLI keeps durable state in ``TMPDIR`` anyway. Every
delete is guarded — the directory on disk must be exactly
``<base>/partyline/<id>``, so a symlink planted at either level is
refused, never followed out.

Sizing never trusts a whole-tree walk to finish: every walk runs under a
time budget and the mount-level summary is cached, so a huge tree costs a
partial answer per tick, never a stalled event loop.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

SIZE_BUDGET_SECONDS = 0.25
SUMMARY_TTL_SECONDS = 5.0
_summary_cache: dict[str, object] = {"at": 0.0, "value": None}


def base_dir() -> Path:
    """The partyline temp base: the pinned or platform temp, plus ``partyline``."""
    pinned = os.environ.get("PARTYLINE_TMP_BASE", "").strip()
    root = Path(pinned) if pinned else Path(tempfile.gettempdir())
    return root / "partyline"


def attachment_tmp_dir(att_id: str) -> Path:
    return base_dir() / att_id


def ensure_tmp_dir(att: dict) -> str:
    """Create (or reuse) this attachment's private temp dir; idempotent per id."""
    base_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    path = attachment_tmp_dir(att["id"])
    path.mkdir(mode=0o700, exist_ok=True)
    return str(path)


def env_for(att: dict) -> dict[str, str]:
    """The ``TMPDIR``/``TMP``/``TEMP`` triple pointing at the attachment's dir."""
    tmp = att.get("tmp_dir")
    return {"TMPDIR": tmp, "TMP": tmp, "TEMP": tmp} if tmp else {}


def guarded_path(att_id: str) -> Path | None:
    """The attachment's temp dir only if the on-disk path is exactly ours."""
    expected = attachment_tmp_dir(att_id)
    if os.path.islink(base_dir()) or os.path.islink(expected):
        return None
    if os.path.realpath(expected) != str(expected):
        return None
    return expected if expected.is_dir() else None


def reap_tmp_dir(att_id: str) -> int | None:
    """Delete one attachment's temp dir; the bytes it freed, or None if absent."""
    path = guarded_path(att_id)
    if path is None:
        return None
    freed = dir_size(path, budget=None)
    shutil.rmtree(path, ignore_errors=True)
    return freed


def line_tmp_ids(db, conv_ids: list[str]) -> list[str]:
    """Attachment ids of the given lines that have a temp dir on disk."""
    ids: list[str] = []
    for conv_id in conv_ids:
        for att in db.list_attachments(conv_id):
            if guarded_path(att["id"]) is not None:
                ids.append(att["id"])
    return ids


def reap_line_tmp(db, conv_id: str) -> int:
    """Reap every temp dir of a line's attachments; the bytes freed."""
    freed = 0
    for att_id in line_tmp_ids(db, [conv_id]):
        freed += reap_tmp_dir(att_id) or 0
    return freed


def reap_missing_tmp(db) -> tuple[int, list[str]]:
    """Reap dirs whose attachment row is gone; the bytes and the ids reaped."""
    freed, reaped = 0, []
    try:
        on_disk = sorted(os.listdir(base_dir()))
    except OSError:
        return 0, []
    for entry in on_disk:
        if db.get_attachment(entry) is None:
            if (bytes_ := reap_tmp_dir(entry)) is not None:
                freed += bytes_
                reaped.append(entry)
    return freed, reaped


def dir_size(path: Path, budget: float | None = SIZE_BUDGET_SECONDS) -> int:
    """Bytes under ``path``, symlinks never followed; a budget caps the walk."""
    deadline = time.monotonic() + budget if budget is not None else None
    total, stack = 0, [str(path)]
    while stack:
        if deadline is not None and time.monotonic() > deadline:
            break
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def tmp_summary(*, cached: bool = True) -> dict[str, int | None]:
    """Mount totals for the temp filesystem plus partyline's share of it.

    Cached for a few seconds so admission checks and riders can ask every
    tick without re-walking; ``cached=False`` forces a fresh answer.
    """
    now = time.monotonic()
    if cached and _summary_cache["value"] is not None and now - _summary_cache["at"] < SUMMARY_TTL_SECONDS:
        return _summary_cache["value"]
    root = base_dir()
    value: dict[str, int | None] = {"tmp_total_bytes": None, "tmp_used_bytes": None}
    try:
        if hasattr(os, "statvfs"):
            stats = os.statvfs(root)
            total = stats.f_blocks * stats.f_frsize
            value["tmp_total_bytes"] = total
            value["tmp_used_bytes"] = total - stats.f_bavail * stats.f_frsize
    except OSError:
        pass
    value["tmp_partyline_bytes"] = dir_size(root) if root.is_dir() else 0
    _summary_cache["at"], _summary_cache["value"] = now, value
    return value


def line_tmp_bytes(db, conv_id: str) -> int:
    """The temp bytes of the given line's live attachments' directories."""
    from .hierarchy import descendants

    total = 0
    for line_id in [conv_id, *descendants(db, conv_id)]:
        for att in db.list_attachments(line_id):
            if att["status"] not in ("starting", "running"):
                continue
            if path := guarded_path(att["id"]):
                total += dir_size(path, budget=SIZE_BUDGET_SECONDS / 4)
    return total


def tmp_resource_line(db, conv_id: str) -> str:
    """One staffing-rider line: the temp mount, and this line's share of it."""
    summary = tmp_summary()
    mount, used = summary["tmp_total_bytes"], summary["tmp_used_bytes"]
    if mount is None or used is None:
        return ""
    name = base_dir().parent.name
    return (f"(tmp: /{name} {used / 2**30:.0f}/{mount / 2**30:.0f} GB · "
            f"this line's processes {line_tmp_bytes(db, conv_id) / 2**30:.1f} GB)")
