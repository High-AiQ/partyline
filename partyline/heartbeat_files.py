"""Snapshots on disk, so a wake is a pointer instead of a wall of JSON.

Inlining the delta worked and immediately created a new problem: every wake
dumped a few kilobytes of JSON into a room humans read. The information was
right, the delivery was not — the same mistake the first heartbeat made, one
level up.

So the payload is written to a file and the reminder carries a pointer to it.
The lead fetches the detail when it wants detail; everyone else sees one line.

The filename is the snapshot's own digest. That makes writing idempotent (the
same state is the same file), makes the pointer self-verifying (fetch it and
you can re-hash it), and means nothing a caller supplies ever reaches a path.
The digest is checked against a strict pattern before it is used as a name, so
the route below cannot be walked out of its directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# The digest as `canonical_hash` produces it: an algorithm label and 16 hex
# characters. Anything else is not a name this module will touch.
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{16}$")

# Old snapshots are evidence, not archives. Enough to look back over a shift.
KEEP_SNAPSHOTS = 200


def snapshot_root(db_path) -> Path:
    """Where snapshots live, derived from the database like `media_root`.

    One rule, no special cases: ``~/.partyline.db`` gives
    ``~/.partyline/heartbeat``, so a database moved onto a NAS takes its
    monitor history with it.
    """
    db = os.path.abspath(os.path.expanduser(str(db_path)))
    return Path(os.path.splitext(db)[0]) / "heartbeat"


def _name(digest: str) -> str:
    if not DIGEST_RE.match(digest or ""):
        raise ValueError("not a snapshot digest")
    return digest.replace(":", "-") + ".json"


def write(db_path, digest: str, snapshot: dict) -> Path:
    """Persist one snapshot, atomically, and return its path.

    Written before the reminder is committed, so a pointer never names a file
    that does not exist. An orphan left by a transaction that then refused to
    post is harmless — it is the same bytes the next identical snapshot would
    write, and pruning collects it.

    The write is rename-into-place: a reader can never see a half-written
    snapshot, which matters because the pointer is fetched by another process.
    """
    root = snapshot_root(db_path)
    root.mkdir(parents=True, exist_ok=True)
    # The directory too: a listing of digests and mtimes is a map of when this
    # tree was busy, and permissions on the files alone do not hide it.
    os.chmod(root, 0o700)
    final = root / _name(digest)
    temporary = final.with_suffix(".json.partial")
    body = json.dumps(snapshot, sort_keys=True, indent=2) + "\n"
    # Created 0600 rather than chmod'd afterwards. Fixing the mode after the
    # rename leaves a window — however brief — in which the finished file is
    # readable at whatever the umask allowed, and the whole point of the rename
    # is that another process may look at any instant.
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        os.unlink(temporary)
        raise
    os.replace(temporary, final)
    return final


def read(db_path, digest: str) -> dict | None:
    """One persisted snapshot, or None. Never opens a path it was handed."""
    try:
        path = snapshot_root(db_path) / _name(digest)
    except ValueError:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def prune(db_path, keep: int = KEEP_SNAPSHOTS) -> int:
    """Drop the oldest snapshots beyond `keep`, and any crash leftovers.

    A `.json.partial` can only exist if a write died between create and
    rename. Nothing will ever finish it, and leaving them means a crash loop
    slowly fills the directory with files no one reads.
    """
    root = snapshot_root(db_path)
    try:
        files = sorted(root.glob("sha256-*.json"), key=lambda p: p.stat().st_mtime)
        abandoned = list(root.glob("*.partial"))
    except OSError:
        return 0
    removed = 0
    for path in [*files[: max(0, len(files) - keep)], *abandoned]:
        try:
            path.unlink()
            removed += 1
        except OSError:  # pragma: no cover - a concurrent prune already won
            pass
    return removed


def pointer(digest: str, snapshot: dict, path: Path) -> str:
    """The one line that rides the reminder instead of the whole payload.

    Counts only, and only the ones that decide whether to look: how many lines
    have news, how many reports are waiting, how many processes are behind.
    Anyone reading the room sees a sentence; the lead that wants the detail
    fetches it.
    """
    lines = snapshot.get("lines", [])
    news = sum(1 for line in lines if line.get("new"))
    behind = sum(len(line.get("agents", [])) for line in lines)
    reports = len(snapshot.get("reports", ()))
    return (
        f"delta: {news} line(s) with new messages, {reports} report(s) waiting, "
        f"{behind} process(es) behind — {digest} at {path}"
    )
