"""Bounded, durable recovery snapshots and ignored-file reclamation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import time

from .line_worktree import _git

logger = logging.getLogger(__name__)

SNAPSHOT_CAP = 64 * 1024 * 1024


def repositories(path: str, *, check_files: bool = False) -> list[str]:
    found = []

    def fail(error):
        raise error  # An unreadable directory is not proof that it holds no repo.

    for directory, dirs, files in os.walk(path, followlinks=False, onerror=fail):
        if directory != path and os.path.lexists(os.path.join(directory, ".git")):
            found.append(os.path.relpath(directory, path))
            dirs[:] = []
        else:
            for name in files if check_files else ():
                mode = os.lstat(os.path.join(directory, name)).st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                    raise ValueError("worktree contains a special file")
            dirs[:] = [name for name in dirs if name != ".git"]
    return sorted(found)


def local_git(path: str) -> bool:
    link = os.path.join(path, ".git")
    if os.path.realpath(path) != path or not os.path.isfile(link) or os.path.islink(link):
        return False
    try:
        top = _git("rev-parse", "--show-toplevel", cwd=path)
        index = _git("rev-parse", "--git-path", "index", cwd=path)
        index_path = Path(path) / index.stdout.strip()
        return (top.returncode == index.returncode == 0 and
                os.path.realpath(top.stdout.strip()) == path and
                index_path.is_file() and not index_path.is_symlink())
    except (OSError, subprocess.SubprocessError):
        return False


def reclaim_ignored(path: str) -> None:
    """Remove only Git-ignored, untracked files, never enter a nested repository."""
    if not local_git(path):
        return  # Never classify an orphan's files using its parent repository.
    try:
        protected = [name.replace(os.sep, "/") for name in repositories(path)]
        done = _git("ls-files", "--others", "--ignored", "--exclude-standard", "-z", cwd=path)
        if done.returncode:
            return
        for name in done.stdout.split("\0"):
            if not name or any(name.rstrip("/") == p or name.startswith(p + "/") for p in protected):
                continue
            target = Path(path) / name
            # Git may report a repository directory as one entry. Never recurse.
            if target.is_symlink() or target.is_file():
                target.unlink()
                parent = target.parent
                while parent != Path(path):
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
    except (OSError, ValueError, subprocess.SubprocessError):
        return  # reclamation is best effort, preservation is mandatory


def snapshot_root(db, root: str, path: str) -> Path:
    key = hashlib.sha256(os.fsencode(os.path.realpath(root))).hexdigest()[:20]
    parts = Path(path).parts
    name = (parts[parts.index(".partyline-worktrees") + 1]
            if ".partyline-worktrees" in parts else Path(path).name)
    return Path(os.path.splitext(db.path)[0]) / "worktree-snapshots" / key / name


def latest_snapshot(db, root: str, path: str) -> str | None:
    directory = snapshot_root(db, root, path)
    snapshots = sorted(directory.glob("*/manifest.json"))
    return str(snapshots[-1].parent) if snapshots else None


def _patch(path: str, target: Path, args: list[str], remaining: int) -> int:
    """Stream binary patches with a hard disk/memory bound."""
    with target.open("wb") as output, subprocess.Popen(
        ["git", "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", *args],
        cwd=path, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as process:
        try:
            size = 0
            while chunk := process.stdout.read(65536):
                size += len(chunk)
                if size > remaining:
                    raise ValueError("snapshot exceeds 64 MiB cap")
                output.write(chunk)
            if process.wait(timeout=30):
                raise ValueError("cannot snapshot Git diff")
            output.flush()
            os.fsync(output.fileno())
            return size
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


class _BoundedWriter:
    def __init__(self, file, limit):
        self.file, self.limit = file, limit

    def tell(self):
        return self.file.tell()

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise ValueError("snapshot exceeds 64 MiB cap")
        return self.file.write(data)


def save_snapshot(db, root: str, path: str) -> str:
    """Preserve index, working diff, and non-ignored untracked files before removal.

    Restore at manifest HEAD: apply index.patch with --index, then worktree.patch,
    then extract untracked.tar. Original Git index and worktree are never modified.
    """
    directory = snapshot_root(db, root, path)
    if Path(path).resolve() in directory.resolve().parents:
        raise ValueError("snapshot storage is inside the worktree")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=directory) as pending:
        dest = Path(pending)
        head = _git("rev-parse", "HEAD", cwd=path)
        conflicts = _git("ls-files", "--unmerged", cwd=path)
        if conflicts.returncode or conflicts.stdout:
            raise ValueError("cannot snapshot an unresolved merge")
        names = _git("ls-files", "--others", "--exclude-standard", "-z", cwd=path)
        if head.returncode or names.returncode:
            raise ValueError("cannot inspect snapshot state")
        used = _patch(path, dest / "index.patch", ["--cached", "HEAD"], SNAPSHOT_CAP)
        used += _patch(path, dest / "worktree.patch", [], SNAPSHOT_CAP - used)
        with (dest / "untracked.tar").open("wb") as output, tarfile.open(
            fileobj=_BoundedWriter(output, SNAPSHOT_CAP - used), mode="w",
        ) as archive:
            for name in filter(None, names.stdout.split("\0")):
                target = Path(path) / name
                mode = target.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                    raise ValueError("snapshot contains a repository or special file")
                used += target.lstat().st_size + 2048
                if used + 10240 > SNAPSHOT_CAP:
                    raise ValueError("snapshot exceeds 64 MiB cap")
                archive.add(target, arcname=name, recursive=False)
        manifest = {"repository": root, "worktree": path, "head": head.stdout.strip(),
                    "restore": "At HEAD, git apply --index index.patch; git apply worktree.patch; "
                               "extract untracked.tar (skip empty patches)."}
        (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if sum(p.stat().st_size for p in dest.iterdir()) > SNAPSHOT_CAP:
            raise ValueError("snapshot exceeds 64 MiB cap")
        for item in dest.iterdir():
            with item.open("rb+") as file:
                os.fsync(file.fileno())
        final = directory / str(time.time_ns())
        os.rename(dest, final)
        # Persist directory entries before the only working copy can disappear.
        if os.name != "nt":
            for folder in (final, directory):
                fd = os.open(folder, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        logger.info("worktree snapshot: %s saved to %s", path, final)
        return str(final)


def record_kept(db, root: str, path: str, reason: str | None) -> None:
    directory = snapshot_root(db, root, path)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (directory / "kept.json").write_text(json.dumps({"reason": reason}), encoding="utf-8")


def kept_reason(db, root: str, path: str) -> str | None:
    try:
        return json.loads((snapshot_root(db, root, path) / "kept.json").read_text())["reason"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
