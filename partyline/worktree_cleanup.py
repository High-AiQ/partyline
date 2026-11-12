"""One preservation policy for retired lines and orphaned managed worktrees."""

import hashlib
import os
import subprocess

from fastapi import HTTPException

from .line_worktree import _git
from .retirement_worktree import refuse_orphan, remove_directory
from .worktree_storage import local_git, reclaim_ignored, record_kept, repositories, save_snapshot


def preserved_refs(root: str, path: str) -> list[str]:
    key = hashlib.sha256(os.fsencode(path)).hexdigest()[:20]
    try:
        done = _git("for-each-ref", "--format=%(refname)",
                    f"refs/partyline/preserved-worktrees/{key}/", cwd=root)
        return done.stdout.splitlines() if done.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        return []


def _preserve_head(root: str, path: str) -> None:
    head = _git("rev-parse", "--verify", "HEAD^{commit}", cwd=path)
    if head.returncode:
        raise ValueError("cannot preserve worktree HEAD")
    preserve_tip(root, path, head.stdout.strip())


def preserve_tip(root: str, path: str, sha: str) -> None:
    key = hashlib.sha256(os.fsencode(path)).hexdigest()[:20]
    ref = f"refs/partyline/preserved-worktrees/{key}/{sha}"
    if _git("update-ref", ref, sha, cwd=root).returncode:
        raise ValueError("cannot preserve worktree commit in repository")


def cleanup(db, root: str, path: str, merged: bool, *, force: bool = False) -> tuple[bool, str | None]:
    """Snapshot merged dirt; explicit force anchors commits. Always protect nested repos."""
    if os.path.realpath(path) != path or os.path.realpath(root) != root:
        return False, "worktree paths must be canonical"
    from .storage_worktrees import in_use
    owner = db._exec("SELECT id FROM conversations WHERE cwd=?", (path,)).fetchone()
    if protection := in_use(db, path, dict(owner) if owner else None):
        return False, protection
    reason = None
    try:
        nested = repositories(path, check_files=True)
        if nested:
            reason = "contains repositories " + ", ".join(nested)
        elif not merged and not force:
            reason = "unmerged commits"
        else:
            refuse_orphan(root, path)
            if not local_git(path):
                raise ValueError("cannot inspect worktree index")
            from .storage_ignored import ignored_reason
            if ignored := ignored_reason(path):
                record_kept(db, root, path, ignored)
                reclaim_ignored(path)
                return False, ignored
            status = _git("status", "--porcelain", cwd=path)
            if status.returncode:
                reason = "cannot inspect Git state"
            elif status.stdout.strip() and not force:
                save_snapshot(db, root, path)
            if reason is None:
                from .storage_git import recover, state
                before = recover(root, path, owner["id"] if owner else None, merged=merged)
                if force and not merged:
                    _preserve_head(root, path)
                record_kept(db, root, path, None)
                with db._runtime_serialized():
                    if protection := in_use(db, path, dict(owner) if owner else None):
                        return False, protection
                    if before != state(root, path, owner["id"] if owner else None):
                        return False, "worktree changed after recovery; retained"
                    if ignored := ignored_reason(path):
                        return False, ignored
                    remove_directory(path, root)
                try:
                    _git("worktree", "remove", "--force", path, cwd=root)
                except (OSError, subprocess.SubprocessError):
                    pass  # Never report failure after successful removal.
                return not os.path.isdir(path), None
    except (OSError, ValueError, subprocess.SubprocessError, HTTPException) as exc:
        reason = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
    try:
        record_kept(db, root, path, reason)
    except OSError:
        pass
    reclaim_ignored(path)
    return False, reason


def task_disposable(spaces: list[dict], cwd: str) -> bool:
    allowed = {os.path.relpath(item["path"], cwd) for item in spaces if item["path"] != cwd}
    try:
        if set(repositories(cwd, check_files=True)) - allowed:
            return False
        return all(not repositories(item["path"], check_files=True)
                   for item in spaces if item["path"] != cwd)
    except (OSError, ValueError):
        return False


def reclaim_task(spaces: list[dict], cwd: str) -> None:
    for path in {cwd, *(item["path"] for item in spaces)}:
        reclaim_ignored(path)
