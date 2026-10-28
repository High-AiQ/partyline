"""Per-attachment temp directories (finding 5.12).

Every spawned process gets its own ``TMPDIR`` under a partyline-owned base,
so one line's engine runs, frames and wheels can neither collide with
another line's artifacts nor hide from reaping. The base is
``$PARTYLINE_TMP_BASE`` when set (tests pin it to their sandbox so nothing
touches the real ``/tmp``; production uses the platform temp), then
``partyline``, then one directory per running partyline instance — twelve
hex of the database path, because several instances share a host and must
never reap each other's directories — then one per attachment id, private
(0700).

Reaping happens only at the moments an attachment ends: a person- or
captain-called close (``DELETE /api/attachments/<id>``), record removal, a
line archive, or a purge — the same moments Greg's finding names. A
restart-driven detach keeps the directory: the same id always resumes into
the same path, and no CLI keeps durable state in ``TMPDIR`` anyway. Every
delete is guarded — the directory on disk must be exactly
``<base>/partyline/<instance>/<id>``, so a symlink planted at any level is
refused, never followed out; the path comparison runs on resolved parents
so macOS's symlinked ``/var/folders`` temp still reaps.

Sizing never trusts a whole-tree walk to finish: one budgeted walk per few
seconds fills the mount totals, the instance total and the per-id sizes
together, and everything else reads the cache — a huge tree costs a partial
answer per tick, never a stalled event loop.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from .temp_mounts import on_tmpfs
from .tmp_levels import private_levels

SIZE_BUDGET_SECONDS = 0.25
SUMMARY_TTL_SECONDS = 5.0
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")
_summary_cache: dict[str, object] = {"at": 0.0, "value": None}


def instance_key() -> str:
    """Twelve hex of the database path: this partyline's temp scope."""
    raw = os.environ.get("PARTYLINE_DB") or "~/.partyline.db"
    return hashlib.sha256(os.path.realpath(os.path.expanduser(raw)).encode()).hexdigest()[:12]


def temp_root(*, mountinfo: str = "/proc/self/mountinfo",
              var_tmp: str = "/var/tmp") -> Path:
    """The pinned or platform temp directory that hosts everything here.

    On Linux, tmpfs is RAM: every byte a process writes there counts
    against its memory budget and the kernel cannot reclaim it. So when the
    default temp directory is tmpfs and a writable ``/var/tmp`` exists on a
    disk-backed filesystem, processes get their temp space there instead.
    The ``PARTYLINE_TMP_BASE`` pin wins over everything (tests), and other
    platforms keep today's behavior.
    """
    pinned = os.environ.get("PARTYLINE_TMP_BASE", "").strip()
    if pinned:
        return Path(pinned)
    current = Path(tempfile.gettempdir())
    if sys.platform == "linux" and on_tmpfs(current, mountinfo):
        candidate = Path(var_tmp)
        if (candidate.is_dir() and not on_tmpfs(candidate, mountinfo)
                and os.access(candidate, os.W_OK | os.X_OK)):
            return candidate
    return current


def base_dir() -> Path:
    return temp_root() / "partyline" / instance_key()


def attachment_tmp_dir(att_id: str) -> Path:
    return base_dir() / att_id


def ensure_tmp_dir(att: dict) -> str:
    """Create (or reuse) this attachment's private temp dir; idempotent per id."""
    return str(private_levels(temp_root(), "partyline", instance_key(), att["id"]))


def env_for(att: dict) -> dict[str, str]:
    """The ``TMPDIR``/``TMP``/``TEMP`` triple pointing at the attachment's dir."""
    tmp = att.get("tmp_dir")
    return {"TMPDIR": tmp, "TMP": tmp, "TEMP": tmp} if tmp else {}


def guarded_path(att_id: str) -> Path | None:
    """The attachment's temp dir only if the on-disk path is exactly ours.

    Parents are compared resolved, so a temp reached through macOS's
    symlinked ``/var/folders`` still matches; a symlink planted on the
    partyline root, the instance dir or the leaf itself is refused.
    """
    instance = base_dir()
    partyline = instance.parent
    expected = instance / att_id
    if any(os.path.islink(p) for p in (partyline, instance, expected)):
        return None
    resolved = os.path.realpath(instance)
    if os.path.realpath(expected) != os.path.join(resolved, att_id):
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
    """Reap leftover dirs in this instance's scope: attachment-shaped names
    whose row is gone. Other instances' scopes are not ours to touch."""
    freed, reaped = 0, []
    try:
        entries = sorted(os.listdir(base_dir()))
    except OSError:
        return 0, []
    for entry in entries:
        if not ID_PATTERN.match(entry):
            continue
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
                    if deadline is not None and time.monotonic() > deadline:
                        break
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


def _usage_snapshot() -> dict:
    """One budgeted walk: mount totals, per-id sizes, the instance total."""
    value: dict[str, object] = {"tmp_total_bytes": None, "tmp_used_bytes": None,
                                "sizes": {}, "tmp_partyline_bytes": 0}
    root = base_dir()
    try:
        if hasattr(os, "statvfs"):
            stats = os.statvfs(root)
            total = stats.f_blocks * stats.f_frsize
            value["tmp_total_bytes"] = total
            value["tmp_used_bytes"] = total - stats.f_bavail * stats.f_frsize
    except OSError:
        pass
    walked = 0
    deadline = time.monotonic() + SIZE_BUDGET_SECONDS
    if root.is_dir():
        try:
            from .tmp_usage_cache import bounded_entries
            entries = bounded_entries(root, deadline)
        except OSError:
            entries = []
        for entry in entries:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            path = root / entry
            if not path.is_dir() or os.path.islink(path):
                continue
            size = dir_size(path, budget=remaining)
            walked += size
            if ID_PATTERN.match(entry):
                value["sizes"][entry] = size
    value["tmp_partyline_bytes"] = walked
    return value


def cached_usage(*, cached: bool = True) -> dict:
    """Read stale data while one background refresh runs."""
    from .tmp_usage_cache import get
    return get(_summary_cache, _usage_snapshot, SUMMARY_TTL_SECONDS, cached=cached)


def tmp_summary(*, cached: bool = True) -> dict[str, int | None]:
    """Mount totals plus partyline's share, from the cached walk."""
    usage = cached_usage(cached=cached)
    return {"tmp_total_bytes": usage["tmp_total_bytes"],
            "tmp_used_bytes": usage["tmp_used_bytes"],
            "tmp_partyline_bytes": usage["tmp_partyline_bytes"]}


def line_tmp_bytes(db, conv_id: str) -> int:
    """The temp bytes of the given line's live attachments, from the cache."""
    from .hierarchy import descendants

    sizes = cached_usage().get("sizes", {})
    total = 0
    for line_id in [conv_id, *descendants(db, conv_id)]:
        for att in db.list_attachments(line_id):
            if att["status"] not in ("starting", "running"):
                continue
            total += sizes.get(att["id"], 0)
    return total


def top_tmp_lines(db, limit: int = 3) -> list[tuple[str, int]]:
    """The lines whose attachments hold the most temp, from the cached walk.

    Finding 5.13: per-line temp is interesting for every line, not only the
    reader's own — the top of the list is where the tmpfs pressure comes
    from.
    """
    sizes = cached_usage().get("sizes", {})
    if not sizes:
        return []
    try:
        totals: dict[str, int] = {}
        for conv in db.list_conversations():
            for att in db.list_attachments(conv["id"]):
                size = sizes.get(att["id"])
                if size:
                    totals[conv["id"]] = totals.get(conv["id"], 0) + size
    except AttributeError:
        # A partial db (role-delivery deltas) cannot answer line queries;
        # the rider then names no top lines rather than failing.
        return []
    ranked = sorted(totals.items(), key=lambda item: -item[1])[:limit]
    named = []
    for conv_id, total in ranked:
        conv = db.get_conversation(conv_id)
        named.append((conv["name"] if conv else conv_id, total))
    return named


def tmp_resource_line(db, conv_id: str) -> str:
    """One staffing-rider line: the temp mount, this line's share of it, and
    the lines that hold the most temp."""
    summary = tmp_summary()
    mount, used = summary["tmp_total_bytes"], summary["tmp_used_bytes"]
    if mount is None or used is None:
        return ""
    try:
        share = line_tmp_bytes(db, conv_id)
    except AttributeError:
        # Some callers hand the rider a partial db (role-delivery deltas);
        # a rider must never fail, so the share reads zero instead.
        share = 0
    name = str(temp_root())
    line = (f"(tmp: {name} {used / 2**30:.0f}/{mount / 2**30:.0f} GB · "
            f"this line's processes {share / 2**30:.1f} GB")
    tops = top_tmp_lines(db)
    if tops:
        listing = ", ".join(f"«{line_name}» {total / 2**30:.1f} GB"
                            for line_name, total in tops)
        line += f" · top tmp: {listing}"
    return line + ")"
